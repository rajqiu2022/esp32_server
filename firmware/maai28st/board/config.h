#pragma once

#include <driver/gpio.h>

constexpr int AUDIO_INPUT_SAMPLE_RATE = 16000;
constexpr int AUDIO_OUTPUT_SAMPLE_RATE = 24000;
constexpr gpio_num_t BOOT_BUTTON_GPIO = GPIO_NUM_0;
constexpr gpio_num_t DISPLAY_CLK_PIN = GPIO_NUM_48;
constexpr gpio_num_t DISPLAY_MOSI_PIN = GPIO_NUM_13;
constexpr gpio_num_t DISPLAY_CS_PIN = GPIO_NUM_40;
constexpr gpio_num_t DISPLAY_DC_PIN = GPIO_NUM_21;
constexpr gpio_num_t DISPLAY_BACKLIGHT_PIN = GPIO_NUM_45;
constexpr gpio_num_t SD_CS_PIN = GPIO_NUM_47;
constexpr gpio_num_t TOUCH_SDA_PIN = GPIO_NUM_39;
constexpr gpio_num_t TOUCH_SCL_PIN = GPIO_NUM_38;
constexpr gpio_num_t TOUCH_RST_PIN = GPIO_NUM_18;
constexpr gpio_num_t TOUCH_INT_PIN = GPIO_NUM_14;
constexpr int DISPLAY_WIDTH = 320;
constexpr int DISPLAY_HEIGHT = 240;
