#pragma once

#include "assets.h"
#include "assets/lang_config.h"
#include "display/lcd_display.h"
#include "lvgl_theme.h"

#include <algorithm>
#include <cstring>
#include <functional>
#include <string>

// Keep the compact layout local to this board; other LCD boards retain their UI.
class MaaiDisplay : public SpiLcdDisplay {
    lv_obj_t* talk_button_ = nullptr;
    lv_obj_t* talk_label_ = nullptr;
    std::string assistant_text_;
    lv_obj_t* assistant_label_ = nullptr;

    void StyleLatestMessage() {
        const auto count = lv_obj_get_child_count(content_);
        if (!count)
            return;
        auto* row = lv_obj_get_child(content_, count - 1);
        auto* bubble = row;
        if (!lv_obj_get_user_data(bubble)) {
            lv_obj_set_width(row, lv_pct(100));
            lv_obj_remove_flag(row, LV_OBJ_FLAG_SCROLLABLE);
            lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
            lv_obj_set_flex_align(row, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_CENTER,
                                  LV_FLEX_ALIGN_CENTER);
            bubble = lv_obj_get_child(row, 0);
        }
        if (!bubble)
            return;
        const auto* role = static_cast<const char*>(lv_obj_get_user_data(bubble));
        if (!role || !strcmp(role, "image"))
            return;
        const bool system = !strcmp(role, "system");
        if (system && row != bubble)
            lv_obj_set_flex_align(row, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER,
                                  LV_FLEX_ALIGN_CENTER);
        lv_obj_remove_flag(bubble, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_style_bg_opa(bubble, system ? LV_OPA_TRANSP : LV_OPA_COVER, 0);
        lv_obj_set_style_radius(bubble, 9, 0);
        lv_obj_set_style_pad_hor(bubble, 10, 0);
        lv_obj_set_style_pad_ver(bubble, 7, 0);
        auto* label = lv_obj_get_child(bubble, 0);
        lv_obj_set_style_max_width(label, 222, 0);
        lv_obj_set_style_text_line_space(label, 3, 0);
        lv_obj_set_width(bubble, LV_SIZE_CONTENT);
        lv_obj_update_layout(content_);
    }

    static void ConfigurePalette(LvglTheme* theme) {
        const bool dark = theme->name() == "dark";
        theme->set_chat_background_color(lv_color_hex(dark ? 0x181818 : 0xEDEDED));
        theme->set_user_bubble_color(lv_color_hex(dark ? 0x2D713A : 0x95EC69));
        theme->set_assistant_bubble_color(lv_color_hex(dark ? 0x303030 : 0xFFFFFF));
        theme->set_system_text_color(lv_color_hex(dark ? 0xAAAAAA : 0x777777));
    }

    void ApplyPalette() {
        const bool dark = current_theme_->name() == "dark";
        auto* theme = static_cast<LvglTheme*>(current_theme_);
        ConfigurePalette(theme);
        lv_obj_set_style_bg_color(content_, theme->chat_background_color(), 0);
        lv_obj_set_style_bg_opa(content_, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(top_bar_, lv_color_hex(dark ? 0x242424 : 0xF7F7F7), 0);
        lv_obj_set_style_bg_opa(top_bar_, LV_OPA_COVER, 0);
        if (bottom_bar_)
            lv_obj_set_style_bg_color(bottom_bar_, lv_color_hex(dark ? 0x242424 : 0xF7F7F7), 0);
    }

public:
    using SpiLcdDisplay::SpiLcdDisplay;
    std::function<void()> on_ready;
    std::function<void()> on_chat;
    std::function<void()> on_theme_changed;

    void SetupUI() override {
        if (IsSetupUICalled())
            return;
        SpiLcdDisplay::SetupUI();
        DisplayLockGuard lock(this);
        if (!lock)
            return;
        // Load the installed common font before Wi-Fi/OTA, so offline settings
        // also have Chinese glyphs. Do not reload speech models or rewrite assets.
        void* font_data = nullptr;
        size_t font_size = 0;
        if (Assets::GetInstance().GetAssetData("font_noto_sans_common_20_4.bin", font_data,
                                               font_size)) {
            auto font = std::make_shared<LvglCBinFont>(font_data);
            if (font->font() && SetTextFont(font))
                ESP_LOGI("MaaiChat", "Common Chinese font loaded before network initialization");
        }
        lv_obj_remove_flag(container_, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_style_pad_all(top_bar_, 0, 0);
        lv_obj_set_height(top_bar_, 40);
        lv_obj_set_layout(top_bar_, LV_LAYOUT_NONE);
        lv_obj_remove_flag(top_bar_, LV_OBJ_FLAG_SCROLLABLE);
        auto* icons = lv_obj_get_child(top_bar_, 1);
        lv_obj_set_parent(network_label_, icons);
        lv_obj_move_to_index(network_label_, 0);
        lv_obj_set_style_pad_column(icons, 3, 0);
        lv_obj_align(icons, LV_ALIGN_RIGHT_MID, -8, 0);
        lv_obj_set_align(status_bar_, LV_ALIGN_TOP_LEFT);
        lv_obj_set_pos(status_bar_, 78, 0);
        lv_obj_set_size(status_bar_, 164, 40);
        lv_obj_set_style_pad_all(status_bar_, 0, 0);
        lv_obj_remove_flag(status_bar_, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_remove_flag(status_bar_, LV_OBJ_FLAG_CLICKABLE);
        for (auto* label : {status_label_, notification_label_}) {
            lv_obj_set_width(label, 164);
            lv_obj_center(label);
        }
        lv_obj_set_style_pad_all(content_, 10, 0);
        lv_obj_set_style_pad_row(content_, 9, 0);
        lv_obj_set_scrollbar_mode(content_, LV_SCROLLBAR_MODE_AUTO);
        lv_obj_set_style_width(content_, 3, LV_PART_SCROLLBAR);
        lv_obj_remove_flag(content_, LV_OBJ_FLAG_SCROLL_ELASTIC);
        lv_obj_add_flag(emoji_image_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_text_font(emoji_label_, GetTheme()->GetTextFont()->font(), 0);
        lv_obj_set_style_text_color(emoji_label_, lv_color_hex(0x888888), 0);
        lv_label_set_text(emoji_label_, "说「你好小智」\n或点击下方开始聊天");
        lv_obj_set_style_text_align(emoji_label_, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(emoji_label_, LV_ALIGN_CENTER, 0, 0);
        lv_obj_remove_flag(emoji_label_, LV_OBJ_FLAG_CLICKABLE);

        bottom_bar_ = lv_obj_create(container_);
        lv_obj_set_size(bottom_bar_, 320, 42);
        lv_obj_set_style_pad_all(bottom_bar_, 4, 0);
        lv_obj_set_style_radius(bottom_bar_, 0, 0);
        lv_obj_set_style_border_width(bottom_bar_, 0, 0);
        lv_obj_remove_flag(bottom_bar_, LV_OBJ_FLAG_SCROLLABLE);
        talk_button_ = lv_button_create(bottom_bar_);
        lv_obj_set_size(talk_button_, 296, 34);
        lv_obj_center(talk_button_);
        lv_obj_set_style_bg_color(talk_button_, lv_color_hex(0xFFFFFF), 0);
        lv_obj_set_style_bg_color(talk_button_, lv_color_hex(0xD8EFD2), LV_STATE_PRESSED);
        lv_obj_set_style_text_color(talk_button_, lv_color_hex(0x333333), 0);
        lv_obj_set_style_border_width(talk_button_, 1, 0);
        lv_obj_set_style_border_color(talk_button_, lv_color_hex(0xDDDDDD), 0);
        lv_obj_set_style_radius(talk_button_, 6, 0);
        lv_obj_set_style_shadow_width(talk_button_, 0, 0);
        talk_label_ = lv_label_create(talk_button_);
        lv_label_set_text(talk_label_, "点击说话");
        lv_obj_center(talk_label_);
        lv_obj_add_event_cb(
            talk_button_,
            [](lv_event_t* event) {
                auto* self = static_cast<MaaiDisplay*>(lv_event_get_user_data(event));
                if (self->on_chat)
                    self->on_chat();
            },
            LV_EVENT_CLICKED, this);
        ApplyPalette();
        if (on_ready)
            on_ready();
        lv_obj_update_layout(lv_screen_active());
        lv_area_t status_area;
        lv_obj_get_coords(status_bar_, &status_area);
        ESP_LOGI("MaaiChat", "Layout ready: header=%ld chat=%ld footer=%ld status=%ld..%ld",
                 static_cast<long>(lv_obj_get_height(top_bar_)),
                 static_cast<long>(lv_obj_get_height(content_)),
                 static_cast<long>(lv_obj_get_height(bottom_bar_)),
                 static_cast<long>(status_area.x1), static_cast<long>(status_area.x2));
    }

    void SetStatus(const char* status) override {
        SpiLcdDisplay::SetStatus(status);
        DisplayLockGuard lock(this);
        if (talk_label_)
            lv_label_set_text(talk_label_, !strcmp(status, Lang::Strings::LISTENING)  ? "结束聆听"
                                           : !strcmp(status, Lang::Strings::SPEAKING) ? "点击打断"
                                                                                      : "点击说话");
    }

    void SetChatMessage(const char* role, const char* text) override {
        if (!role || !text)
            return;
        // A firmware version is useful in logs, not as the first chat bubble.
        if (!strcmp(role, "system") &&
            !strncmp(text, "makerfabs-maai28st/", strlen("makerfabs-maai28st/")))
            return;
        DisplayLockGuard lock(this);
        if (!content_)
            return;
        if (!strcmp(role, "assistant") && *text && assistant_label_ &&
            lv_obj_is_valid(assistant_label_) && assistant_text_.size() + strlen(text) < 2048) {
            assistant_text_ += "\n";
            assistant_text_ += text;
            lv_label_set_text(assistant_label_, assistant_text_.c_str());
            lv_obj_update_layout(content_);
            lv_obj_scroll_to_view_recursive(assistant_label_, LV_ANIM_OFF);
            return;
        }
        assistant_label_ = nullptr;
        assistant_text_.clear();
        size_t length = std::min<size_t>(strlen(text), 2048);
        while (length && (static_cast<unsigned char>(text[length]) & 0xC0) == 0x80)
            --length;
        const std::string bounded(text, length);
        SpiLcdDisplay::SetChatMessage(role, bounded.c_str());
        if (!*text) {
            if (!lv_obj_get_child_count(content_))
                lv_obj_remove_flag(emoji_label_, LV_OBJ_FLAG_HIDDEN);
            return;
        }
        lv_obj_add_flag(emoji_label_, LV_OBJ_FLAG_HIDDEN);
        StyleLatestMessage();
        if (!strcmp(role, "assistant")) {
            assistant_label_ = chat_message_label_;
            assistant_text_ = bounded;
        }
        lv_obj_scroll_to_view_recursive(lv_obj_get_child(content_, -1), LV_ANIM_OFF);
    }

    void SetPreviewImage(std::unique_ptr<LvglImage> image) override {
        if (!image)
            return;
        DisplayLockGuard lock(this);
        if (!content_)
            return;
        // A VGA preview owns ~600 KiB. Keep only the latest photo in RAM.
        for (int32_t i = lv_obj_get_child_count(content_) - 1; i >= 0; --i) {
            auto* row = lv_obj_get_child(content_, i);
            const auto* role = static_cast<const char*>(lv_obj_get_user_data(row));
            if (role && !strcmp(role, "image"))
                lv_obj_delete(row);
        }
        assistant_label_ = nullptr;
        assistant_text_.clear();
        if (lv_obj_get_child_count(content_) >= 20) {
            chat_message_label_ = nullptr;
            lv_obj_delete(lv_obj_get_child(content_, 0));
        }
        SpiLcdDisplay::SetPreviewImage(std::move(image));
        lv_obj_remove_flag(lv_obj_get_child(content_, -1), LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_flag(emoji_label_, LV_OBJ_FLAG_HIDDEN);
    }

    void ClearChatMessages() override {
        DisplayLockGuard lock(this);
        assistant_label_ = nullptr;
        assistant_text_.clear();
        SpiLcdDisplay::ClearChatMessages();
    }

    void SetEmotion(const char*) override {}  // Status stays in the header; leave room for chat.
    void SetHideSubtitle(bool) override {}    // The bottom bar is a voice control, not a subtitle.

    void SetTheme(Theme* theme) override {
        ConfigurePalette(static_cast<LvglTheme*>(theme));
        SpiLcdDisplay::SetTheme(theme);
        DisplayLockGuard lock(this);
        if (content_)
            ApplyPalette();
        if (emoji_label_)
            lv_obj_set_style_text_font(emoji_label_, GetTheme()->GetTextFont()->font(), 0);
        if (on_theme_changed)
            on_theme_changed();
    }
};
