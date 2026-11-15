// A dialog: black scrim at 60 %, panel-raised, radius.float, at most 560 px. Eyebrow, heading title, the body (its
// children), then the actions at the end (quiet "Cancel" before the primary). Esc cancels; Enter takes `accepted`
// unless focus is in a multi-line field. open() / close().
import QtQuick
import QtQuick.Templates as T

T.Popup {
    id: dialog
    property string eyebrow: ""
    property string title: ""
    default property alias body: bodyColumn.data
    property alias actions: actionRow.data
    signal accepted()
    signal rejected()

    parent: T.Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(560, (parent ? parent.width : 560) - 32)
    implicitHeight: contentHeight + topPadding + bottomPadding
    height: Math.min(implicitHeight, (parent ? parent.height : implicitHeight) - 32)
    modal: true
    focus: true
    padding: 0
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside
    onClosed: if (!acceptedNow) rejected(); else acceptedNow = false
    property bool acceptedNow: false
    function accept() { acceptedNow = true; accepted(); close() }

    T.Overlay.modal: Rectangle {
        color: Theme.alpha("black", 0.6)
        Behavior on opacity { NumberAnimation { duration: Theme.motion.slow } }
    }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motion.slow; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.ease } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.motion.base } }

    background: Rectangle {
        color: Theme.panelRaised
        radius: Theme.radius.float
        border.width: 1
        border.color: Theme.lineStrong
    }
    Shortcut {
        sequences: ["Return", "Enter"]
        enabled: dialog.opened
        onActivated: if (!(dialog.contentItem.Window.activeFocusItem instanceof TextEdit)) dialog.accept()
    }
    contentItem: Column {
        Column {
            width: parent.width
            topPadding: 18; leftPadding: 20; rightPadding: 20; bottomPadding: 6
            spacing: 4
            Label { textStyle: "eyebrow"; text: dialog.eyebrow; color: Theme.text3; visible: dialog.eyebrow !== "" }
            Label { textStyle: "heading"; text: dialog.title; visible: dialog.title !== ""; width: parent.width - 40; wrapMode: Text.Wrap }
        }
        Column {
            id: bodyColumn
            x: 20
            width: parent.width - 40
            topPadding: 8; bottomPadding: 16
            spacing: 12
        }
        Rectangle { width: parent.width; height: 1; color: Theme.line; visible: actionRow.children.length > 0 }
        Item {
            width: parent.width
            height: actionRow.children.length > 0 ? actionRow.implicitHeight + 24 : 0
            Row {
                id: actionRow
                anchors.right: parent.right; anchors.rightMargin: 20
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
            }
        }
    }
}
