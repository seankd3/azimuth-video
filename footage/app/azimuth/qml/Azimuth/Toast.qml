// The toast: bottom-centre of the panel the action happened in (put it in that panel; it fills it). Float surface,
// body text, one optional action ("Undo"). 4 s, 8 s with an action; hovering holds it; a new toast replaces the old.
// show(text) or show(text, "Undo", function () { ... }).
import QtQuick

Item {
    id: toasts
    anchors.fill: parent
    z: 40
    property string text: ""
    property string action: ""
    property var actionFn: null
    property real bottomMargin: 14
    readonly property bool showing: card.visible

    function show(text, action, callback) {
        toasts.text = text
        toasts.action = action || ""
        toasts.actionFn = callback || null
        card.visible = true
        rise.restart()
        timer.interval = toasts.action ? 8000 : 4000
        timer.restart()
    }
    function hide() { card.visible = false; timer.stop() }

    Timer { id: timer; onTriggered: if (hover.hovered) restart(); else toasts.hide() }

    Item {
        id: card
        visible: false
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: toasts.bottomMargin
        width: row.implicitWidth + 22
        height: Math.max(row.implicitHeight + 16, Theme.size.control + 10)
        HoverHandler { id: hover }
        Float { anchors.fill: parent }
        Row {
            id: row
            anchors.verticalCenter: parent.verticalCenter
            x: 14
            spacing: 12
            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: toasts.text
                width: Math.min(implicitWidth, Math.min(520, toasts.width - 24) - 22 - (act.visible ? act.implicitWidth + 12 : 0))
            }
            Button {
                id: act
                visible: toasts.action !== ""
                small: true
                text: toasts.action
                onClicked: { if (toasts.actionFn) toasts.actionFn(); toasts.hide() }
            }
        }
        ParallelAnimation {
            id: rise
            NumberAnimation { target: card; property: "opacity"; from: 0; to: 1; duration: Theme.motion.base }
            NumberAnimation { target: card; property: "anchors.bottomMargin"; from: toasts.bottomMargin - 6; to: toasts.bottomMargin
                              duration: Theme.motion.base; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.ease }
        }
    }
}
