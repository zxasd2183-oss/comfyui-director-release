plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.gms.google-services")
}

android {
    namespace = "cn.borealos.jipite"
    compileSdk = 35
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
}
