// A clip on a timeline: a panel-raised block over its filmstrip (the clip's children), ringed 2 px in the accent when
// current, with trim handles at both ends that light in the accent on hover. A drag on a handle reports
// trimStarted(end), trimMoved(end, dx) in pixels from where it started, trimEnded(end); end is "in" or "out".
// label: the badge at the bottom-left.
import QtQuick

Item {
    id: clip
    property bool current: false
    property bool trimmable: true
    property string label: ""
    property string labelIcon: ""
    default property alias content: body.data
    signal trimStarted(string end)
    signal trimMoved(string end, real dx)
    signal trimEnded(string end)
    readonly property bool trimming: inHandle.pressed || outHandle.pressed

    component Handle: MouseArea {
        id: handle
        property real from: 0
        signal started()
        signal moved(real dx)
        signal ended()
        width: 6
        z: 3
        hoverEnabled: true
        cursorShape: Qt.SizeHorCursor
        preventStealing: true
        onPressed: m => { from = mapToItem(null, m.x, 0).x; started() }
        onPositionChanged: m => { if (pressed) moved(mapToItem(null, m.x, 0).x - from) }
        onReleased: ended()
        Rectangle {
            anchors.fill: parent
            radius: 2
            color: Theme.accent
            opacity: handle.containsMouse || handle.pressed ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.motion.fast } }
        }
    }

    // The clip's own parts are listed here, so the children an app gives it go into the body.
    data: [
        Rectangle {
            id: body
            anchors.fill: parent
            radius: 2
            color: Theme.panelRaised
            clip: true
        },
        Rectangle {                                  // a hairline, or the current clip's ring
            anchors.fill: parent
            radius: 2
            color: "transparent"
            border.width: clip.current ? 2 : 1
            border.color: clip.current ? Theme.accent : Theme.line
            z: 2
        },
        Badge { corner: "bl"; text: clip.label; iconName: clip.labelIcon; visible: clip.label !== "" && clip.width > 40; z: 2 },
        Handle {
            id: inHandle
            x: 0; height: clip.height; enabled: clip.trimmable
            onStarted: clip.trimStarted("in"); onMoved: dx => clip.trimMoved("in", dx); onEnded: clip.trimEnded("in")
        },
        Handle {
            id: outHandle
            x: clip.width - width; height: clip.height; enabled: clip.trimmable
            onStarted: clip.trimStarted("out"); onMoved: dx => clip.trimMoved("out", dx); onEnded: clip.trimEnded("out")
        }
    ]
}
