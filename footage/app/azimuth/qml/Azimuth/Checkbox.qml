// A checkbox, for choices that apply on confirm: 14 px, radius 2; on, off, or partial (tristate).
import QtQuick
import QtQuick.Templates as T

T.CheckBox {
    id: cb
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    spacing: 9
    opacity: enabled ? 1 : 0.4
    implicitWidth: indicator.width + (text ? spacing + contentItem.implicitWidth : 0)
    implicitHeight: Math.max(14, contentItem.implicitHeight)

    indicator: Rectangle {
        width: 14; height: 14; radius: 2
        y: (cb.height - height) / 2
        readonly property bool marked: cb.checkState !== Qt.Unchecked
        color: marked ? Theme.accent : Theme.well
        border.width: 1
        border.color: marked ? Theme.accent : Theme.lineHover
        Icon {
            anchors.centerIn: parent
            size: 12
            name: cb.checkState === Qt.PartiallyChecked ? "minus" : "check"
            color: Theme.accentInk
            visible: parent.marked
        }
        FocusRing { target: cb; targetRadius: 2 }
    }
    contentItem: Label {
        leftPadding: cb.indicator.width + cb.spacing
        text: cb.text
        color: cb.hovered ? Theme.text : Theme.text2
        visible: cb.text !== ""
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
