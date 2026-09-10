plugins {
    id("com.android.library")           version "8.5.2"
    id("org.jetbrains.kotlin.android")  version "1.9.24"
    id("app.cash.paparazzi")            version "1.3.4"
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
}

dependencies {
    implementation("androidx.compose.material3:material3:1.2.1")
    implementation("androidx.compose.ui:ui-tooling-preview:1.6.8")
    testImplementation("junit:junit:4.13.2")
}
