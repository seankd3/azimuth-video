// A button. kind: quiet (outlined, the default), primary (accent: one per view), go (Shoot, Import, Render), danger,
// bare (no frame). small: the 22 px height. icon.name: an icon from the set; with no text it is a square icon button,
// framed on hover only. key: a key cap before the label ("⏎ Apply"). tip: the tooltip, its name and key.
// checkable + checked: the one "on" state (accent fill). busy: the label carries the progress ("Rendering 42%").
import QtQuick
import QtQuick.Templates as T

T.Button {
    id: b
    property string kind: "quiet"
    property bool small: false
    property string key: ""
    property string tip: ""
    property bool busy: false
    readonly property bool iconOnly: text === "" && icon.name !== ""
    readonly property bool on: checked

    readonly property color fill: on ? Theme.accent
        : kind === "primary" ? Theme.accent
        : kind === "go" ? Theme.go
        : kind === "danger" ? (hovered ? Theme.reject : Theme.rejectTint)
        : hovered ? Theme.rowHover : "transparent"
    readonly property color edge: on ? Theme.accent
        : kind === "primary" ? Theme.accent
        : kind === "go" ? Theme.go
        : kind === "danger" ? Theme.reject
        : kind === "bare" ? "transparent"
        : iconOnly ? (hovered ? Theme.lineStrong : "transparent")
        : hovered ? Theme.lineHover : Theme.lineStrong
    readonly property color ink: on ? Theme.accentInk
        : kind === "primary" ? Theme.accentInk
        : kind === "go" ? Theme.goInk
        : kind === "danger" ? (hovered ? Theme.rejectInk : Theme.reject)
        : (kind === "bare" || iconOnly) ? (hovered ? Theme.text : Theme.text2)
        : Theme.text

    implicitHeight: small ? Theme.size.control_small : Theme.size.control
    implicitWidth: iconOnly ? implicitHeight : contentItem.implicitWidth + (small ? 16 : 24)
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    opacity: enabled ? 1 : 0.4
    scale: pressed ? 0.97 : 1
    Behavior on scale { NumberAnimation { duration: Theme.motion.fast; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.ease } }

    background: Rectangle {
        radius: Theme.radius.control
        color: b.fill
        border.width: 1
        border.color: b.edge
        Behavior on color { ColorAnimation { duration: Theme.motion.fast } }
        Behavior on border.color { ColorAnimation { duration: Theme.motion.fast } }
        FocusRing { target: b }
    }
    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 7
            KeyCap {
                visible: b.key !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: b.key; inButton: true; ink: b.ink; parentFill: b.fill.a > 0 ? b.fill : Theme.panel
            }
            Icon {
                visible: b.icon.name !== ""
                anchors.verticalCenter: parent.verticalCenter
                name: b.icon.name; color: b.ink
            }
            Label {
                visible: b.text !== ""
                anchors.verticalCenter: parent.verticalCenter
                textStyle: "button"; text: b.text; color: b.ink
            }
        }
    }
    HoverHandler { cursorShape: !b.enabled ? Qt.ForbiddenCursor : b.busy ? Qt.BusyCursor : Qt.PointingHandCursor }
    Tip { text: b.tip; visible: b.tip !== "" && b.hovered }
}
