package preview

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import org.junit.Rule
import org.junit.Test

/**
 * Renders the snippet the bot dropped into Snippet.kt.
 *
 * Paparazzi draws Compose on the desktop JVM through LayoutLib — no emulator,
 * no APK, no device. That is the whole reason the Android side of this bot is
 * fast and free while the iOS side needs a Mac.
 *
 * Theme and device come from the environment because the bot re-runs this same
 * test with different values when someone taps an inline button.
 */
class PreviewTest {

    private val dark = System.getenv("PREVIEW_THEME") != "light"

    @get:Rule
    val paparazzi = Paparazzi(
        deviceConfig = if (System.getenv("PREVIEW_DEVICE") == "tablet")
            DeviceConfig.NEXUS_10 else DeviceConfig.PIXEL_6,
        theme = if (dark) "android:Theme.Material.NoActionBar"
                else       "android:Theme.Material.Light.NoActionBar",
    )

    @Test
    fun render() {
        paparazzi.snapshot { Preview() }
    }
}
