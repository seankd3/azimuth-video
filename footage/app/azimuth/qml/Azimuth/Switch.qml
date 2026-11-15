// A switch, for settings that apply at once: 28x16 track, line-strong off, accent on, a 12 px knob.
import QtQuick
import QtQuick.Templates as T

T.Switch {
    id: sw
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    spacing: 10
    opacity: enabled ? 1 : 0.4
    implicitWidth: indicator.width + (text ? spacing + contentItem.implicitWidth : 0)
    implicitHeight: Math.max(16, contentItem.implicitHeight)

    indicator: Rectangle {
        width: 28; height: 16; radius: 8
        y: (sw.height - height) / 2
        color: sw.checked ? Theme.accent : Theme.lineStrong
        Behavior on color { ColorAnimation { duration: Theme.motion.fast } }
        Rectangle {
            width: 12; height: 12; radius: 6; y: 2
            x: sw.checked ? 14 : 2
            color: sw.checked ? Theme.accentInk : Theme.text
            Behavior on x { NumberAnimation { duration: Theme.motion.base; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.ease } }
        }
        FocusRing { target: sw; targetRadius: 8 }
    }
    contentItem: Label {
        leftPadding: sw.indicator.width + sw.spacing
        text: sw.text
        color: sw.hovered ? Theme.text : Theme.text2
        visible: sw.text !== ""
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
