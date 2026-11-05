// Colours and sizes, light and dark; the same palette the HTML client had.
pragma Singleton
import QtQuick

QtObject {
    readonly property bool dark: Qt.styleHints.colorScheme === Qt.ColorScheme.Dark

    readonly property color background: dark ? "#0a0a0a" : "#fafaf7"
    readonly property color foreground: dark ? "#fafafa" : "#0a0a0a"
    readonly property color card: dark ? "#171717" : "#ffffff"
    readonly property color primary: dark ? "#e5e5e5" : "#171717"
    readonly property color primaryInk: dark ? "#171717" : "#fafafa"
    readonly property color secondary: dark ? "#262626" : "#f5f5f5"
    readonly property color muted: dark ? "#a1a1a1" : "#737373"
    readonly property color border: dark ? Qt.rgba(1, 1, 1, 0.10) : "#e5e5e5"
    readonly property color inputBorder: dark ? Qt.rgba(1, 1, 1, 0.15) : "#e5e5e5"
    readonly property color inputBg: dark ? Qt.rgba(1, 1, 1, 0.045) : "transparent"
    readonly property color ring: dark ? "#737373" : "#a1a1a1"
    readonly property color hover: dark ? Qt.rgba(1, 1, 1, 0.05) : Qt.rgba(0.94, 0.94, 0.94, 0.7)
    readonly property color destructive: dark ? "#ff6467" : "#e7000b"
    readonly property color accent: dark ? "#3fcf8e" : "#00754a"
    readonly property color accentInk: dark ? "#04140c" : "#ffffff"

    readonly property int radius: 10
    readonly property int fontSize: 14
    readonly property string mono: "monospace"
}
