import QtQuick

Column {
    id: root
    property string label
    property alias text: field.text
    property alias placeholder: field.placeholder
    property alias input: field.input
    signal accepted()
    width: parent ? parent.width : 200
    spacing: 6
    Text { textFormat: Text.PlainText; text: root.label; color: Theme.foreground; font.pixelSize: Theme.fontSize; font.weight: Font.Medium }
    Field { id: field; width: parent.width; onAccepted: root.accepted() }
}
