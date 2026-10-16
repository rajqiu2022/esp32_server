# Makerfabs MAAI28ST

MaTouch AI ESP32-S3 2.8 inch ST7789V, 16 MB flash and 8 MB octal PSRAM.
Display: SPI3 CLK48/MOSI13/CS40/DC21, backlight45; unused SD CS47 held high.
GT911: SDA39/SCL38/RST18/INT14, 0x5D, landscape 320x240.
MAX98357: BCLK20/WS1/DOUT19. INMP441: BCLK42/WS2/DIN41.
BOOT GPIO0 toggles conversation; taps in the chat area do the same.
The bottom-right Settings button opens persistent volume (1–100) and
brightness (5–100%) sliders plus a confirmed Wi-Fi reconfiguration action.
Settings touches do not toggle chat. Slider values apply and persist on release.
UART0 through CH340K is required; native USB uses the speaker pins.

Build with ESP-IDF 6.0.1 or newer:

```powershell
python scripts/build.py makerfabs-maai28st --name makerfabs-maai28st --language zh-CN
```

This variant uses the upstream official service by default. An existing
`wifi/ota_url` NVS override connects to a private backend and survives app-only
updates. For the official service, bind the activation code at https://xiaozhi.me/.
Wi-Fi provisioning uses XiaoZhi's standard access-point configuration page.
The previous self-hosted build is preserved separately in the workspace's
local/xiaozhi-maai28st-firmware directory.

## Onboard RGB lamp

The V1.1 schematic connects the WS2812B level shifter and BOOT button to GPIO0.
The board-specific driver uses open-drain output only during a single-pixel RMT
transmission, then immediately restores input with pull-up. It refuses a command
while BOOT is held. No status LED handler owns this lamp.

MCP tools: `self.light.get_state`, `self.light.set_power`,
`self.light.set_color`, `self.light.set_brightness`.
State reports the last successfully transmitted command, not optical feedback.
The lamp starts off, at a remembered-in-session brightness of 20%. Lamp state
is not written to NVS. Existing Wi-Fi, audio and touch settings are preserved.

IDF 6 `gpio_set_direction(...OUTPUT...)` clears peripheral routing. The lamp driver
captures the RMT-assigned output signal during initialization and reconnects it
after every direction change, then reads back the route and open-drain mode.
A brief blue startup test bypasses networking and the model; shutdown is scheduled
without blocking initialization. A later user light command cancels auto-shutdown.

GPIO0 button click callbacks ignore the 600 ms window after lamp transmission,
to discard scanner events caused by the LED waveform. BOOT toggles chat only in
idle/listening/speaking states; Wi-Fi setup is available in the touch settings.
This prevents a startup pulse from entering provisioning while Wi-Fi initializes.

## OV3660 still camera

Uses the factory 24-pin camera connector: XCLK9, D7..D0=46/3/8/16/6/4/5/7,
VSYNC11, HREF10, PCLK17. SCCB reuses the touch controller's I2C0 on SDA39/SCL38;
the camera must not create a second I2C master. XCLK uses LEDC timer/channel 1,
leaving backlight timer/channel 0 untouched.

One VGA RGB565 framebuffer is allocated in PSRAM. Boot checks a real frame and
only exposes the standard `self.camera.take_photo` tool when the camera works.
Voice, touch and lamp still initialize if the camera is absent. The common
camera implementation creates a display preview and uploads a JPEG on request.
The backend must supply an authenticated vision URL/token through MCP initialize
and use a model with image input support. There is no continuous video upload.
