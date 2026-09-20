allprojects {
    repositories {
        google()
        mavenCentral()
        maven { url = uri("https://jitpack.io") }   // usb_serial's serial driver
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}

// audio_stream_player (and similar AGP 9 plugins) ship Kotlin without applying
// kotlin-android. This project sets android.builtInKotlin=false, so those
// sources never compile and GeneratedPluginRegistrant cannot find the class.
subprojects {
    pluginManager.withPlugin("com.android.library") {
        if (file("src/main/kotlin").exists() &&
            !pluginManager.hasPlugin("org.jetbrains.kotlin.android")) {
            pluginManager.apply("org.jetbrains.kotlin.android")
        }
    }
    pluginManager.withPlugin("org.jetbrains.kotlin.android") {
        extensions.findByType<org.jetbrains.kotlin.gradle.dsl.KotlinAndroidProjectExtension>()
            ?.compilerOptions
            ?.jvmTarget
            ?.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
