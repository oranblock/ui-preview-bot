package preview

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * Renders the snippet, and — the reason this is Roborazzi rather than Paparazzi
 * — can CLICK it first.
 *
 * Paparazzi draws through LayoutLib and has no notion of touch, so its pictures
 * are always the initial state. Roborazzi runs the real Compose test rule under
 * Robolectric, still on the JVM with no emulator, so a button can be pressed and
 * the result captured.
 *
 * Two things are read from the environment because the bot re-runs this same
 * test with different values when someone taps in Telegram:
 *   PREVIEW_THEME / PREVIEW_DEVICE  appearance
 *   PREVIEW_CLICKS                  comma-separated node indices to click, in order
 *
 * It also writes buttons.txt, one clickable label per line. That file is what
 * turns the real UI's buttons into Telegram's buttons — the names come from the
 * view itself rather than from anything hardcoded.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
// sdk is pinned. Robolectric picks a default from the manifest, and NATIVE
// graphics only draw on a recent one — on the wrong sdk the composition still
// lays out and reports its semantics while rendering nothing, which is exactly
// what a blank png with a correctly-detected button list looks like.
@Config(sdk = [34], qualifiers = "w411dp-h891dp-xhdpi")
class PreviewTest {

    @get:Rule
    val rule = createComposeRule()

    @Test
    fun render() {
        val dark = System.getenv("PREVIEW_THEME") != "light"

        // The device switch has to happen before the first composition, and
        // qualifiers in @Config are compile-time constants, so set it here.
        if (System.getenv("PREVIEW_DEVICE") == "tablet") {
            RuntimeEnvironment.setQualifiers("+w800dp-h1280dp-xhdpi")
        }

        rule.setContent {
            MaterialTheme(colorScheme = if (dark) darkColorScheme() else lightColorScheme()) {
                Surface(modifier = Modifier.fillMaxSize()) { Preview() }
            }
        }

        // Clicks are applied before anything is written, so the screenshot and
        // the button list both describe the state the viewer is actually seeing.
        System.getenv("PREVIEW_CLICKS").orEmpty()
            .split(",").filter { it.isNotBlank() }
            .forEach { idx ->
                val i = idx.trim().toIntOrNull() ?: return@forEach
                val nodes = rule.onAllNodes(hasClickAction())
                runCatching { nodes[i].performClick() }
                    .onFailure { println("click $i failed: ${it.message}") }
                rule.waitForIdle()
            }

        val labels = rule.onAllNodes(hasClickAction()).fetchSemanticsNodes().map { n ->
            n.config.getOrNull(SemanticsProperties.Text)?.joinToString(" ")?.take(24)
                ?: n.config.getOrNull(SemanticsProperties.ContentDescription)?.joinToString(" ")?.take(24)
                ?: "button"
        }
        val out = File("build/buttons.txt")
        out.parentFile?.mkdirs()
        out.writeText(labels.joinToString("\n"))
        println("clickable: ${labels.size} -> $labels")

        // Compose settles asynchronously; capturing before it does yields the
        // empty frame.
        rule.waitForIdle()
        rule.onRoot().captureRoboImage("build/preview.png")
    }
}
