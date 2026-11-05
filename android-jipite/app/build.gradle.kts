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

    // Optional GitHub Actions signing. Only configured builds consume the
    // private keystore; UI-only debug builds remain unaffected.
    val signedStore = System.getenv("JIPITE_SIGNING_KEYSTORE_FILE")
    if (!signedStore.isNullOrBlank()) {
        signingConfigs {
            create("jipiteRelease") {
                storeFile = file(signedStore)
                storePassword = System.getenv("JIPITE_SIGNING_STORE_PASSWORD")
                    ?: error("JIPITE_SIGNING_STORE_PASSWORD missing")
                keyAlias = System.getenv("JIPITE_SIGNING_KEY_ALIAS")
                    ?: error("JIPITE_SIGNING_KEY_ALIAS missing")
                keyPassword = System.getenv("JIPITE_SIGNING_KEY_PASSWORD")
                    ?: error("JIPITE_SIGNING_KEY_PASSWORD missing")
            }
        }
        buildTypes {
            getByName("release") {
                signingConfig = signingConfigs.getByName("jipiteRelease")
                isMinifyEnabled = false
            }
        }
    }
    flavorDimensions += "push"
    productFlavors {
        create("manual") { dimension = "push" }  // No SDK / vendor review required
        create("google") { dimension = "push" }
        create("xiaomi") { dimension = "push" }
    }
    defaultConfig {
        applicationId = "cn.borealos.jipite"
        minSdk = 30
        targetSdk = 35
        versionCode = 17
        versionName = "0.10.5"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    testImplementation("junit:junit:4.13.2")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.fragment:fragment-ktx:1.8.5")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("com.microsoft.identity.client:msal:8.6.0")
    add("googleImplementation", "com.google.firebase:firebase-messaging:24.1.2")
    // Install the official AAR locally before building the xiaomi flavor.
    // It is not redistributed in this public source repository.
    add("xiaomiImplementation", files("libs/MiPush_SDK_Client.aar"))
}
