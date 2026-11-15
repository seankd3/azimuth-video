// What floats over everything (menus, popovers, the select list, chips over the stage): float surface, radius.float,
// 1 px line-strong, one shadow (0 8px 24px, black at 35 % dark, 12 % light). Panels never cast shadows; floats do.
// The shadow is drawn as soft layers rather than an effect, so it costs nothing and renders on every backend.
import QtQuick

Item {
    id: f
    property color color: Theme.float
    property color edge: Theme.lineStrong
    property real radius: Theme.radius.float
    property bool shadow: true

    Repeater {                                       // 0 8px 24px: six widening layers under the surface
        model: f.shadow ? 6 : 0
        Rectangle {
            required property int index
            readonly property real spread: (index + 1) * 2
            x: -spread; y: 8 - spread
            width: f.width + 2 * spread; height: f.height + 2 * spread
            radius: f.radius + spread
            color: Theme.alpha(Theme.shadow, Theme.shadow.a / 6 * (1 - index / 7))
        }
    }
    Rectangle {
        anchors.fill: parent
        radius: f.radius
        color: f.color
        border.width: 1
        border.color: f.edge
    }
}
