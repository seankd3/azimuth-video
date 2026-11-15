// A panel's head: title (title style), count (label, text-3), tools at the end (60 % until the head is hovered).
// Children go into the tools row.
import QtQuick

Item {
    id: head
    property string title: ""
    property string count: ""
    default property alias tools: toolRow.data
    implicitHeight: Theme.size.panel_head
    implicitWidth: titles.implicitWidth + toolRow.implicitWidth + 40

    // The head's own parts are listed here, so the children an app gives it go to the tools row.
    data: [
        MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton; readonly property bool hovered: containsMouse },
        Row {
            id: titles
            x: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            Label { textStyle: "title"; text: head.title }
            Label { textStyle: "label"; text: head.count; color: Theme.text3; visible: head.count !== "" }
        },
        Row {
            id: toolRow
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            opacity: hover.hovered || head.activeFocus ? 1 : 0.6
            Behavior on opacity { NumberAnimation { duration: Theme.motion.base } }
        },
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
    ]
}
