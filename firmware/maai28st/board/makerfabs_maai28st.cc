#include <led_strip.h>
#include "application.h"
#include "button.h"
#include "codecs/no_audio_codec.h"
#include "config.h"
#include "display/lcd_display.h"
#include "esp32_camera.h"
#include "lvgl_font.h"
#include "maai_chat_display.h"
#include "mcp_server.h"
#include "wifi_board.h"

#include <driver/i2c_master.h>
#include <driver/spi_master.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_panel_vendor.h>
#include <esp_lcd_touch_gt911.h>
#include <esp_log.h>
#include <esp_lvgl_port.h>
#include <esp_rom_gpio.h>
#include <algorithm>
#include <atomic>
#include <functional>

static constexpr const char* TAG = "MAAI28ST";

class MakerfabsMaai28st : public WifiBoard {
    Button boot_button_{BOOT_BUTTON_GPIO};
    LcdDisplay* display_ = nullptr;
    i2c_master_bus_handle_t touch_bus_ = nullptr;
    std::unique_ptr<Esp32Camera> camera_;
    lv_obj_t* settings_panel_ = nullptr;
    lv_obj_t* settings_shade_ = nullptr;
    lv_obj_t* settings_entry_ = nullptr;
    lv_obj_t* wifi_confirm_ = nullptr;
    lv_obj_t* volume_value_ = nullptr;
    lv_obj_t* brightness_value_ = nullptr;
    lv_obj_t* volume_slider_ = nullptr;
    lv_obj_t* brightness_slider_ = nullptr;
    std::shared_ptr<LvglFont> settings_font_;
    led_strip_handle_t light_strip_ = nullptr;
    uint32_t light_rmt_signal_ = 0;
    esp_timer_handle_t light_test_timer_ = nullptr;
    bool light_boot_test_pending_ = false;
    std::atomic<uint32_t> light_activity_ms_{0};
    bool light_on_ = false;
    int light_brightness_ = 20;
    std::string light_color_ = "white";
    uint8_t light_r_ = 255, light_g_ = 255, light_b_ = 255;

    std::string LightState() const {
        return std::string("{\"on\":") + (light_on_ ? "true" : "false") +
               ",\"brightness\":" + std::to_string(light_brightness_) + ",\"color\":\"" +
               light_color_ + "\",\"feedback\":\"last_successfully_sent_command\"}";
    }

    ToolResult ApplyLight(bool on, int brightness, const std::string& color, uint8_t red,
                          uint8_t green, uint8_t blue) {
        // GPIO0 is shared with BOOT: never drive it push-pull, and release the
        // data line immediately after the short WS2812 transmission. The LED
        // retains its latched color while BOOT continues to work as an input.
        if (!gpio_get_level(BOOT_BUTTON_GPIO)) {
            return std::unexpected("BOOT button is held; release it and retry light control");
        }
        light_activity_ms_.store(static_cast<uint32_t>(esp_timer_get_time() / 1000));
        if (gpio_set_direction(BOOT_BUTTON_GPIO, GPIO_MODE_INPUT_OUTPUT_OD) != ESP_OK) {
            return std::unexpected("Cannot configure light output");
        }
        // IDF 6 gpio_output_enable() resets the matrix to a plain GPIO signal.
        // Reattach the actual signal assigned by the RMT driver after changing
        // direction, while keeping the shared BOOT line open-drain.
        esp_rom_gpio_connect_out_signal(BOOT_BUTTON_GPIO, light_rmt_signal_, false, false);
        gpio_io_config_t routed = {};
        if (gpio_get_io_config(BOOT_BUTTON_GPIO, &routed) != ESP_OK ||
            routed.sig_out != light_rmt_signal_ || !routed.od || !routed.ie) {
            gpio_set_direction(BOOT_BUTTON_GPIO, GPIO_MODE_INPUT);
            gpio_pullup_en(BOOT_BUTTON_GPIO);
            return std::unexpected("Light GPIO routing check failed; command not sent");
        }
        ESP_LOGI(TAG, "LIGHT route verified: signal=%lu open_drain=%d input=%d",
                 static_cast<unsigned long>(routed.sig_out), routed.od, routed.ie);
        auto err = led_strip_set_pixel(light_strip_, 0, on ? red * brightness / 100 : 0,
                                       on ? green * brightness / 100 : 0,
                                       on ? blue * brightness / 100 : 0);
        if (err == ESP_OK)
            err = led_strip_refresh(light_strip_);
        const auto released = gpio_set_direction(BOOT_BUTTON_GPIO, GPIO_MODE_INPUT);
        gpio_pullup_en(BOOT_BUTTON_GPIO);
        light_activity_ms_.store(static_cast<uint32_t>(esp_timer_get_time() / 1000));
        ESP_LOGI(TAG, "LIGHT GPIO released: level=%d", gpio_get_level(BOOT_BUTTON_GPIO));
        if (err != ESP_OK || released != ESP_OK) {
            return std::unexpected("Light transmission failed; state unchanged");
        }
        light_boot_test_pending_ = false;
        light_on_ = on;
        light_brightness_ = brightness;
        light_color_ = color;
        light_r_ = red;
        light_g_ = green;
        light_b_ = blue;
        ESP_LOGI(TAG, "LIGHT applied: on=%d color=%s brightness=%d; BOOT input restored", on,
                 color.c_str(), brightness);
        return LightState();
    }

    void InitializeLightTools() {
        led_strip_config_t config = {};
        config.strip_gpio_num = BOOT_BUTTON_GPIO;
        config.max_leds = 1;
        config.led_model = LED_MODEL_WS2812;
        config.color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB;
        led_strip_rmt_config_t rmt = {};
        rmt.resolution_hz = 10 * 1000 * 1000;
        const auto err = led_strip_new_rmt_device(&config, &rmt, &light_strip_);
        gpio_io_config_t initial_route = {};
        const auto route_err = gpio_get_io_config(BOOT_BUTTON_GPIO, &initial_route);
        light_rmt_signal_ = initial_route.sig_out;
        gpio_set_direction(BOOT_BUTTON_GPIO, GPIO_MODE_INPUT);
        gpio_pullup_en(BOOT_BUTTON_GPIO);
        if (err != ESP_OK || route_err != ESP_OK) {
            ESP_LOGW(TAG, "RGB unavailable: %s", esp_err_to_name(err));
            return;
        }
        const auto cleared = ApplyLight(false, 20, "white", 255, 255, 255);
        if (!cleared)
            ESP_LOGW(TAG, "Initial lamp clear deferred");
        auto& mcp = McpServer::GetInstance();
        mcp.AddTool("self.light.get_state",
                    "Read the onboard RGB lamp's last commanded power, color and brightness. No "
                    "optical sensor is present.",
                    PropertyList(),
                    [this](const PropertyList&) -> ToolResult { return LightState(); });
        mcp.AddTool("self.light.set_power",
                    "Turn the onboard lamp on or off; preserve its current color and brightness.",
                    PropertyList({Property("on", kPropertyTypeBoolean)}),
                    [this](const PropertyList& p) -> ToolResult {
                        return ApplyLight(p["on"].value<bool>(), light_brightness_, light_color_,
                                          light_r_, light_g_, light_b_);
                    });
        mcp.AddTool("self.light.set_brightness",
                    "Set the onboard lamp brightness from 0 to 100 percent; 0 turns it off, higher "
                    "values turn it on. Read state first for relative changes.",
                    PropertyList({Property("brightness", kPropertyTypeInteger, 0, 100)}),
                    [this](const PropertyList& p) -> ToolResult {
                        const int brightness = p["brightness"].value<int>();
                        return ApplyLight(brightness > 0,
                                          brightness > 0 ? brightness : light_brightness_,
                                          light_color_, light_r_, light_g_, light_b_);
                    });
        mcp.AddTool(
            "self.light.set_color",
            "Change the onboard lamp color and turn it on. Supported color names: white, "
            "warm_white, red, green, blue, yellow, cyan, purple, orange.",
            PropertyList({Property("color", kPropertyTypeString)}),
            [this](const PropertyList& p) -> ToolResult {
                const auto color = p["color"].value<std::string>();
                struct Color {
                    const char* name;
                    uint8_t r, g, b;
                };
                static constexpr Color colors[] = {
                    {"white", 255, 255, 255}, {"warm_white", 255, 180, 80}, {"red", 255, 0, 0},
                    {"green", 0, 255, 0},     {"blue", 0, 0, 255},          {"yellow", 255, 255, 0},
                    {"cyan", 0, 255, 255},    {"purple", 180, 0, 255},      {"orange", 255, 80, 0}};
                for (const auto& c : colors) {
                    if (color == c.name)
                        return ApplyLight(true, light_brightness_, color, c.r, c.g, c.b);
                }
                return std::unexpected("Unsupported color; choose a documented color name");
            });
        ESP_LOGI(TAG, "RGB light MCP tools ready on shared GPIO0; BOOT input preserved");
        // A brief visible startup diagnostic bypasses Wi-Fi, ASR and the model.
        const auto test = ApplyLight(true, 30, "blue", 0, 0, 255);
        if (test) {
            light_boot_test_pending_ = true;
            esp_timer_create_args_t timer = {};
            timer.name = "rgb_boot_test";
            timer.arg = this;
            timer.callback = [](void* arg) {
                auto* self = static_cast<MakerfabsMaai28st*>(arg);
                Application::GetInstance().Schedule([self]() {
                    if (self->light_boot_test_pending_)
                        self->ApplyLight(false, 20, "white", 255, 255, 255);
                });
            };
            if (esp_timer_create(&timer, &light_test_timer_) == ESP_OK)
                esp_timer_start_once(light_test_timer_, 10000000);
        }
    }

    static lv_color_t Ink() { return lv_color_hex(0x252525); }

    lv_obj_t* Label(lv_obj_t* parent, const char* text, int x, int y) {
        auto* label = lv_label_create(parent);
        lv_label_set_text(label, text);
        lv_obj_set_pos(label, x, y);
        return label;
    }

    lv_obj_t* MakeButton(lv_obj_t* parent, const char* text, int x, int y, int w, int h) {
        auto* button = lv_button_create(parent);
        lv_obj_set_pos(button, x, y);
        lv_obj_set_size(button, w, h);
        lv_obj_set_style_bg_color(button, Ink(), 0);
        lv_obj_set_style_text_color(button, lv_color_white(), 0);
        lv_obj_set_style_radius(button, 12, 0);
        lv_obj_set_style_shadow_width(button, 0, 0);
        auto* label = lv_label_create(button);
        lv_label_set_text(label, text);
        lv_obj_center(label);
        return button;
    }

    lv_obj_t* Slider(lv_obj_t* parent, int y, int minimum) {
        auto* slider = lv_slider_create(parent);
        lv_obj_set_pos(slider, 14, y);
        lv_obj_set_size(slider, 260, 10);
        lv_slider_set_range(slider, minimum, 100);
        lv_obj_set_style_bg_color(slider, lv_color_hex(0xE4E4E4), LV_PART_MAIN);
        lv_obj_set_style_bg_color(slider, lv_color_hex(0x07C160), LV_PART_INDICATOR);
        lv_obj_set_style_bg_color(slider, lv_color_hex(0x07C160), LV_PART_KNOB);
        lv_obj_set_ext_click_area(slider, 14);
        return slider;
    }

    void RefreshControlFont() {
        auto font = display_->GetTheme()->GetTextFont();
        if (!font)
            return;
        if (settings_entry_)
            lv_obj_set_style_text_font(settings_entry_, font->font(), 0);
        if (settings_shade_)
            lv_obj_set_style_text_font(settings_shade_, font->font(), 0);
        if (settings_panel_)
            lv_obj_set_style_text_font(settings_panel_, font->font(), 0);
        // Rebind raw LVGL style pointers before releasing the previous owner.
        settings_font_ = std::move(font);
    }

    void ShowSettings(bool show) {
        if (!settings_shade_)
            return;
        if (show) {
            const int volume = GetAudioCodec()->output_volume();
            const int brightness = GetBacklight()->brightness();
            lv_slider_set_value(volume_slider_, volume, LV_ANIM_OFF);
            lv_slider_set_value(brightness_slider_, brightness, LV_ANIM_OFF);
            lv_label_set_text_fmt(volume_value_, "%d", volume);
            lv_label_set_text_fmt(brightness_value_, "%d%%", brightness);
            lv_obj_remove_flag(settings_shade_, LV_OBJ_FLAG_HIDDEN);
            lv_anim_delete(settings_panel_, nullptr);
            lv_anim_t animation;
            lv_anim_init(&animation);
            lv_anim_set_var(&animation, settings_panel_);
            lv_anim_set_values(&animation, 28, 42);
            lv_anim_set_duration(&animation, 120);
            lv_anim_set_exec_cb(&animation, [](void* object, int32_t y) {
                lv_obj_set_y(static_cast<lv_obj_t*>(object), y);
            });
            lv_anim_start(&animation);
            ESP_LOGI(TAG, "Quick settings opened");
        } else {
            lv_anim_delete(settings_panel_, nullptr);
            lv_obj_add_flag(settings_shade_, LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(wifi_confirm_, LV_OBJ_FLAG_HIDDEN);
        }
    }

    void InitializeControls() {
        DisplayLockGuard lock(display_);
        if (!lock)
            return;
        settings_font_ = display_->GetTheme()->GetTextFont();
        auto* layer = lv_layer_top();
        auto* entry = MakeButton(layer, "设置", 4, 2, 70, 36);
        settings_entry_ = entry;
        lv_obj_set_style_bg_opa(entry, LV_OPA_TRANSP, 0);
        lv_obj_set_style_text_color(entry, lv_color_hex(0x07C160), 0);
        lv_obj_set_style_text_font(entry, settings_font_->font(), 0);
        lv_obj_add_event_cb(
            entry,
            [](lv_event_t* event) {
                static_cast<MakerfabsMaai28st*>(lv_event_get_user_data(event))->ShowSettings(true);
            },
            LV_EVENT_CLICKED, this);

        settings_shade_ = lv_obj_create(layer);
        lv_obj_set_size(settings_shade_, DISPLAY_WIDTH, DISPLAY_HEIGHT);
        lv_obj_set_style_pad_all(settings_shade_, 0, 0);
        lv_obj_set_style_radius(settings_shade_, 0, 0);
        lv_obj_set_style_border_width(settings_shade_, 0, 0);
        lv_obj_set_style_bg_color(settings_shade_, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(settings_shade_, LV_OPA_20, 0);
        lv_obj_set_style_text_font(settings_shade_, settings_font_->font(), 0);
        lv_obj_remove_flag(settings_shade_, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_event_cb(
            settings_shade_,
            [](lv_event_t* event) {
                auto* self = static_cast<MakerfabsMaai28st*>(lv_event_get_user_data(event));
                if (lv_event_get_target(event) == self->settings_shade_)
                    self->ShowSettings(false);
            },
            LV_EVENT_CLICKED, this);
        settings_panel_ = lv_obj_create(settings_shade_);
        lv_obj_set_pos(settings_panel_, 6, 42);
        lv_obj_set_size(settings_panel_, 308, 192);
        lv_obj_set_style_pad_all(settings_panel_, 12, 0);
        lv_obj_set_style_border_width(settings_panel_, 0, 0);
        lv_obj_set_style_radius(settings_panel_, 14, 0);
        lv_obj_set_style_shadow_width(settings_panel_, 14, 0);
        lv_obj_set_style_shadow_opa(settings_panel_, LV_OPA_20, 0);
        lv_obj_set_style_bg_color(settings_panel_, lv_color_hex(0xFAFAFA), 0);
        lv_obj_set_style_text_color(settings_panel_, Ink(), 0);
        lv_obj_set_style_text_font(settings_panel_, settings_font_->font(), 0);
        lv_obj_remove_flag(settings_panel_, LV_OBJ_FLAG_SCROLLABLE);
        Label(settings_panel_, "音量", 0, 0);
        volume_value_ = Label(settings_panel_, "35", 238, 0);
        volume_slider_ = Slider(settings_panel_, 36, 1);
        Label(settings_panel_, "亮度", 0, 62);
        brightness_value_ = Label(settings_panel_, "75%", 226, 62);
        brightness_slider_ = Slider(settings_panel_, 98, 5);
        auto* wifi = MakeButton(settings_panel_, "Wi-Fi 配网", 0, 132, 284, 34);
        lv_obj_add_event_cb(
            wifi,
            [](lv_event_t* event) {
                auto* self = static_cast<MakerfabsMaai28st*>(lv_event_get_user_data(event));
                lv_obj_remove_flag(self->wifi_confirm_, LV_OBJ_FLAG_HIDDEN);
            },
            LV_EVENT_CLICKED, this);
        for (auto* slider : {volume_slider_, brightness_slider_}) {
            lv_obj_add_event_cb(
                slider,
                [](lv_event_t* event) {
                    auto* self = static_cast<MakerfabsMaai28st*>(lv_event_get_user_data(event));
                    auto* slider = static_cast<lv_obj_t*>(lv_event_get_target(event));
                    const int value = lv_slider_get_value(slider);
                    const bool volume = slider == self->volume_slider_;
                    if (lv_event_get_code(event) == LV_EVENT_VALUE_CHANGED) {
                        lv_label_set_text_fmt(
                            volume ? self->volume_value_ : self->brightness_value_,
                            volume ? "%d" : "%d%%", value);
                    } else if (lv_event_get_code(event) == LV_EVENT_RELEASED) {
                        Application::GetInstance().Schedule([self, value, volume]() {
                            if (volume)
                                self->GetAudioCodec()->SetOutputVolume(value);
                            else
                                self->GetBacklight()->SetBrightness(value, true);
                            ESP_LOGI(TAG, "Touch settings saved: %s=%d",
                                     volume ? "volume" : "brightness", value);
                        });
                    }
                },
                LV_EVENT_ALL, this);
        }
        wifi_confirm_ = lv_obj_create(settings_shade_);
        lv_obj_set_size(wifi_confirm_, 288, 208);
        lv_obj_set_pos(wifi_confirm_, 16, 16);
        lv_obj_set_style_bg_color(wifi_confirm_, lv_color_hex(0xFAFAFA), 0);
        lv_obj_set_style_border_width(wifi_confirm_, 0, 0);
        lv_obj_set_style_pad_all(wifi_confirm_, 10, 0);
        lv_obj_remove_flag(wifi_confirm_, LV_OBJ_FLAG_SCROLLABLE);
        Label(wifi_confirm_, "重新配网？", 0, 0);
        auto* hint = Label(wifi_confirm_,
                           "将断开当前连接。\n用手机连接板子热点，\n按提示设置新的 Wi-Fi。", 0, 40);
        lv_obj_set_width(hint, 268);
        lv_label_set_long_mode(hint, LV_LABEL_LONG_WRAP);
        auto* cancel = MakeButton(wifi_confirm_, "取消", 0, 150, 116, 38);
        auto* confirm = MakeButton(wifi_confirm_, "开始配网", 128, 150, 140, 38);
        lv_obj_add_event_cb(
            cancel,
            [](lv_event_t* event) {
                auto* self = static_cast<MakerfabsMaai28st*>(lv_event_get_user_data(event));
                lv_obj_add_flag(self->wifi_confirm_, LV_OBJ_FLAG_HIDDEN);
            },
            LV_EVENT_CLICKED, this);
        lv_obj_add_event_cb(
            confirm,
            [](lv_event_t* event) {
                auto* self = static_cast<MakerfabsMaai28st*>(lv_event_get_user_data(event));
                self->ShowSettings(false);
                Application::GetInstance().Schedule([self]() { self->EnterWifiConfigMode(); });
            },
            LV_EVENT_CLICKED, this);
        ShowSettings(false);
        ESP_LOGI(TAG, "Top-left quick settings ready: volume, brightness, Wi-Fi");
    }

    static void ToggleChat() {
        Application::GetInstance().Schedule([]() { Application::GetInstance().ToggleChatState(); });
    }

    void InitializeDisplay() {
        // The unmounted SD card shares the LCD SPI bus.
        ESP_ERROR_CHECK(gpio_set_direction(SD_CS_PIN, GPIO_MODE_OUTPUT));
        ESP_ERROR_CHECK(gpio_set_level(SD_CS_PIN, 1));
        spi_bus_config_t bus = {};
        bus.mosi_io_num = DISPLAY_MOSI_PIN;
        bus.miso_io_num = GPIO_NUM_NC;
        bus.sclk_io_num = DISPLAY_CLK_PIN;
        bus.quadwp_io_num = GPIO_NUM_NC;
        bus.quadhd_io_num = GPIO_NUM_NC;
        bus.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * 2;
        ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &bus, SPI_DMA_CH_AUTO));

        esp_lcd_panel_io_spi_config_t io = {};
        io.cs_gpio_num = DISPLAY_CS_PIN;
        io.dc_gpio_num = DISPLAY_DC_PIN;
        io.spi_mode = 0;
        io.pclk_hz = 40 * 1000 * 1000;
        io.trans_queue_depth = 10;
        io.lcd_cmd_bits = 8;
        io.lcd_param_bits = 8;
        esp_lcd_panel_io_handle_t panel_io = nullptr;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI3_HOST, &io, &panel_io));
        esp_lcd_panel_dev_config_t cfg = {};
        cfg.reset_gpio_num = GPIO_NUM_NC;
        cfg.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
        cfg.bits_per_pixel = 16;
        esp_lcd_panel_handle_t panel = nullptr;
        ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(panel_io, &cfg, &panel));
        ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel, true));
        ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(panel, true));
        ESP_ERROR_CHECK(esp_lcd_panel_mirror(panel, true, false));
        display_ = new MaaiDisplay(panel_io, panel, DISPLAY_WIDTH, DISPLAY_HEIGHT, 0, 0, true,
                                   false, true);
        static_cast<MaaiDisplay*>(display_)->on_ready = [this]() { InitializeControls(); };
        static_cast<MaaiDisplay*>(display_)->on_chat = []() { ToggleChat(); };
        static_cast<MaaiDisplay*>(display_)->on_theme_changed = [this]() { RefreshControlFont(); };
    }

    void InitializeCamera() {
        camera_config_t config = {};
        config.pin_pwdn = -1;
        config.pin_reset = -1;
        config.pin_xclk = 9;
        // The OV3660 and GT911 share I2C0. Reuse the existing master bus.
        config.pin_sccb_sda = -1;
        config.pin_sccb_scl = -1;
        config.sccb_i2c_port = I2C_NUM_0;
        config.pin_d7 = 46;
        config.pin_d6 = 3;
        config.pin_d5 = 8;
        config.pin_d4 = 16;
        config.pin_d3 = 6;
        config.pin_d2 = 4;
        config.pin_d1 = 5;
        config.pin_d0 = 7;
        config.pin_vsync = 11;
        config.pin_href = 10;
        config.pin_pclk = 17;
        config.xclk_freq_hz = 20000000;
        // Backlight owns timer/channel 0; changing its timer would blank the LCD.
        config.ledc_timer = LEDC_TIMER_1;
        config.ledc_channel = LEDC_CHANNEL_1;
        config.pixel_format = PIXFORMAT_RGB565;
        config.frame_size = FRAMESIZE_VGA;
        config.jpeg_quality = 12;
        config.fb_count = 1;
        config.fb_location = CAMERA_FB_IN_PSRAM;
        config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
        camera_ = std::make_unique<Esp32Camera>(config);
        auto* sensor = esp_camera_sensor_get();
        if (!sensor) {
            camera_.reset();
            ESP_LOGW(TAG, "Camera unavailable; voice, touch and lamp remain available");
            return;
        }
        auto* frame = esp_camera_fb_get();
        if (frame) {
            ESP_LOGI(TAG, "Camera frame verified: PID=0x%04x %ux%u %u bytes", sensor->id.PID,
                     static_cast<unsigned>(frame->width), static_cast<unsigned>(frame->height),
                     static_cast<unsigned>(frame->len));
            esp_camera_fb_return(frame);
        } else {
            ESP_LOGW(TAG, "Camera frame test failed; camera tool disabled");
            camera_.reset();
        }
    }

    void InitializeTouch() {
        i2c_master_bus_config_t bus = {};
        bus.i2c_port = I2C_NUM_0;
        bus.sda_io_num = TOUCH_SDA_PIN;
        bus.scl_io_num = TOUCH_SCL_PIN;
        bus.clk_source = I2C_CLK_SRC_DEFAULT;
        bus.glitch_ignore_cnt = 7;
        bus.flags.enable_internal_pullup = true;
        ESP_ERROR_CHECK(i2c_new_master_bus(&bus, &touch_bus_));
        esp_lcd_panel_io_i2c_config_t io = {};
        io.dev_addr = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS;
        io.control_phase_bytes = 1;
        io.lcd_cmd_bits = 16;
        io.flags.disable_control_phase = 1;
        io.scl_speed_hz = 400000;
        esp_lcd_panel_io_handle_t touch_io = nullptr;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(touch_bus_, &io, &touch_io));
        static esp_lcd_touch_io_gt911_config_t driver = {};
        driver.dev_addr = io.dev_addr;
        esp_lcd_touch_config_t cfg = {};
        cfg.x_max = DISPLAY_WIDTH;
        cfg.y_max = DISPLAY_HEIGHT;
        cfg.rst_gpio_num = TOUCH_RST_PIN;
        cfg.int_gpio_num = TOUCH_INT_PIN;
        cfg.driver_data = &driver;
        // Match the verified Arduino rotation-1 mapping, without applying a
        // second display rotation to coordinates.
        cfg.process_coordinates = [](esp_lcd_touch_handle_t, uint16_t* x, uint16_t* y, uint16_t*,
                                     uint8_t* count, uint8_t) {
            for (uint8_t i = 0; i < *count; ++i) {
                const auto raw_x = x[i];
                x[i] = std::min<uint16_t>(y[i], DISPLAY_WIDTH - 1);
                y[i] = DISPLAY_HEIGHT - 1 - std::min<uint16_t>(raw_x, DISPLAY_HEIGHT - 1);
            }
        };
        esp_lcd_touch_handle_t touch = nullptr;
        auto err = esp_lcd_touch_new_i2c_gt911(touch_io, &cfg, &touch);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "Touch unavailable: %s", esp_err_to_name(err));
            esp_lcd_panel_io_del(touch_io);
            return;
        }
        lvgl_port_touch_cfg_t lv_touch = {};
        lv_touch.disp = lv_display_get_default();
        lv_touch.handle = touch;
        auto* input = lvgl_port_add_touch(&lv_touch);
        if (input)
            ESP_LOGI(TAG, "GT911 ready; scroll chat, use voice button or top-left settings");
    }

public:
    MakerfabsMaai28st() {
        InitializeDisplay();
        InitializeTouch();
        InitializeCamera();
        InitializeLightTools();
        boot_button_.OnClick([this]() {
            // The button scanner also sees RGB pulses on shared GPIO0. Ignore
            // their delayed click events; never enter provisioning mid-startup.
            const auto now = static_cast<uint32_t>(esp_timer_get_time() / 1000);
            if (now - light_activity_ms_.load() < 600)
                return;
            Application::GetInstance().Schedule([this]() {
                const auto now = static_cast<uint32_t>(esp_timer_get_time() / 1000);
                if (now - light_activity_ms_.load() < 600)
                    return;
                const auto state = Application::GetInstance().GetDeviceState();
                if (state == kDeviceStateIdle || state == kDeviceStateListening ||
                    state == kDeviceStateSpeaking) {
                    Application::GetInstance().ToggleChatState();
                }
            });
        });
        GetBacklight()->RestoreBrightness();
    }

    AudioCodec* GetAudioCodec() override {
        // Two independent standard-I2S buses: MAX98357 speaker and INMP441 mic.
        // GPIO19/20 are audio, so the console must use the CH340K/UART0.
        static NoAudioCodecSimplex codec(AUDIO_INPUT_SAMPLE_RATE, AUDIO_OUTPUT_SAMPLE_RATE,
                                         GPIO_NUM_20, GPIO_NUM_1, GPIO_NUM_19, GPIO_NUM_42,
                                         GPIO_NUM_2, GPIO_NUM_41);
        return &codec;
    }

    Display* GetDisplay() override { return display_; }

    Camera* GetCamera() override { return camera_.get(); }

    Backlight* GetBacklight() override {
        static PwmBacklight backlight(DISPLAY_BACKLIGHT_PIN, false);
        return &backlight;
    }
};

DECLARE_BOARD(MakerfabsMaai28st);
