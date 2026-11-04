plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.gms.google-services") apply false
}

// Google Services plugin is only required for Google/FCM builds.
// Xiaomi Mi Push builds do NOT need a Firebase project or google-services.json.
if (providers.gradleProperty("enableFirebase").orNull == "true") {
    apply(plugin = "com.google.gms.google-services")
}

android {
    buildFeatures { buildConfig = true }
    namespace = "cn.borealos.jipite"
    compileSdk = 35
    flavorDimensions += "push"
    productFlavors {
        create("google") { dimension = "push" }
        create("xiaomi") { dimension = "push" }
    }
    defaultConfig {
        applicationId = "cn.borealos.jipite"
        minSdk = 30
        targetSdk = 35
        versionCode = 1
        versionName = "0.6.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.fragment:fragment-ktx:1.8.5")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("com.microsoft.identity.client:msal:8.6.0")
    implementation("com.google.firebase:firebase-messaging:24.1.2")
    // Install the official AAR locally before building the xiaomi flavor.
    // It is not redistributed in this public source repository.
    add("xiaomiImplementation", files("libs/MiPush_SDK_Client.aar"))
}
