plugins {
    id("com.android.library")          version "8.5.2"
    id("org.jetbrains.kotlin.android") version "1.9.24"
    id("io.github.takahirom.roborazzi") version "1.26.0"
}

android {
    namespace  = "preview"
    compileSdk = 34
    defaultConfig { minSdk = 24 }
    buildFeatures { compose = true }
    composeOptions { kotlinCompilerExtensionVersion = "1.5.14" }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    sourceSets["test"].java.srcDir("src/test/kotlin")
    // Robolectric needs the real Android resources, unlike Paparazzi's LayoutLib.
    testOptions {
        unitTests {
            isIncludeAndroidResources = true
            all {
                // Belt and braces with @GraphicsMode: without native graphics
                // Robolectric draws nothing at all and every capture is blank.
                it.systemProperty("robolectric.graphicsMode", "NATIVE")
                it.systemProperty("robolectric.pixelCopyRenderMode", "hardware")
            }
        }
    }
}

dependencies {
    implementation("androidx.compose.material3:material3:1.2.1")
    implementation("androidx.compose.ui:ui-tooling-preview:1.6.8")
    implementation("androidx.activity:activity-compose:1.9.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.12.2")
    testImplementation("androidx.test.ext:junit:1.1.5")
    // The reason for the whole switch: this brings the Compose test rule into a
    // JVM test, so a node can be CLICKED before the screenshot is taken.
    testImplementation("androidx.compose.ui:ui-test-junit4:1.6.8")
    debugImplementation("androidx.compose.ui:ui-test-manifest:1.6.8")
    testImplementation("io.github.takahirom.roborazzi:roborazzi:1.26.0")
    testImplementation("io.github.takahirom.roborazzi:roborazzi-compose:1.26.0")
}
