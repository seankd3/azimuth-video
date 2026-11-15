// The zoom chip, at the stage's bottom-centre on an 82 % panel float: Fit · Fill · 1:1 · 2:1, and the live
// percentage. mode: "fit", "fill", "1:1", "2:1", or "" while free (wheel). picked(mode) when one is chosen.
import QtQuick

Item {
    id: chip
    property string mode: "fit"
    property real percent: 100
    signal picked(string mode)
    readonly property var modes: ["fit", "fill", "1:1", "2:1"]
    implicitWidth: row.implicitWidth + 6
    implicitHeight: row.implicitHeight + 6

    Float { anchors.fill: parent; color: Theme.alpha(Theme.panel, 0.82); edge: Theme.line; shadow: false }
    Row {
        id: row
        x: 3; y: 3
        spacing: 6
        Segmented {
            small: true
            model: ["Fit", "Fill", "1:1", "2:1"]
            currentIndex: chip.modes.indexOf(chip.mode)
            onActivated: i => chip.picked(chip.modes[i])
        }
        Label {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(44, implicitWidth + 12)
            horizontalAlignment: Text.AlignHCenter
            textStyle: "code"
            color: Theme.text2
            text: Math.round(chip.percent) + "%"
        }
    }
}
