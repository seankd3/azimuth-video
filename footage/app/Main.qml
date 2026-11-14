// Azimuth Video: cut, trim and frame an edit. Everything shown is computed from backend.shots, which the backend
// recomputes from the edit after every change; the window only keeps the playhead, what is playing, and drags.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 1600; height: 1000
    visible: true
    title: backend.name ? backend.name + " — Azimuth Video" : "Azimuth Video"
    color: theme.background

    readonly property var theme: backend.theme
    readonly property var shots: backend.shots
    property real playhead: 0
    property bool playing: false
    property bool framing: false          // the frame editor is open on the shot under the playhead
    property bool graded: true
    property int active: 0                // which deck plays
    readonly property var decks: [deckA, deckB]
    readonly property int current: locate(playhead)
    property string note: ""

    font.pixelSize: 14
    palette.window: theme.background; palette.windowText: theme.foreground
    palette.button: theme.raised; palette.buttonText: theme.foreground
    palette.base: theme.raised; palette.text: theme.foreground
    palette.highlight: theme.accent; palette.highlightedText: theme.background

    function locate(t) {
        for (let i = 0; i < shots.length; i++)
            if (t < shots[i].at + shots[i].duration - 1e-6) return i
        return shots.length - 1
    }
    function sourceTime(i, t) { return shots[i].start + Math.max(0, t - shots[i].at) }

    // Put the playhead at edit time t: the active deck on its shot, the other waiting on the next.
    function seek(t) {
        if (!shots.length) return
        playhead = Math.max(0, Math.min(t, backend.duration - 0.001))
        const i = locate(playhead)
        decks[active].cue(shots[i], sourceTime(i, playhead))
        decks[1 - active].cue(i + 1 < shots.length ? shots[i + 1] : null, i + 1 < shots.length ? shots[i + 1].start : 0)
        if (playing) decks[active].player.play()
    }
    function play() {
        if (!shots.length) return
        if (playhead >= backend.duration - 0.05) seek(0)
        playing = true
        decks[active].player.play()
    }
    function pause() {
        playing = false
        deckA.player.pause(); deckB.player.pause()
        seek(playhead)
    }
    function cut() {                       // the active shot ended: the waiting deck takes over
        const i = current
        if (i + 1 >= shots.length) { pause(); return }
        decks[active].player.pause()
        active = 1 - active
        decks[active].player.play()
        playhead = shots[i + 1].at
        decks[1 - active].cue(i + 2 < shots.length ? shots[i + 2] : null, i + 2 < shots.length ? shots[i + 2].start : 0)
    }
    function step(seconds) { if (playing) pause(); seek(playhead + seconds) }
    function edge(direction) {
        const edges = shots.map(s => s.at).concat([backend.duration])
        const next = direction > 0 ? edges.find(e => e > playhead + 0.01) : edges.slice().reverse().find(e => e < playhead - 0.01)
        if (next !== undefined) step(next - playhead)
    }
    function say(text) { note = text; noteTimer.restart() }

    Connections {
        target: backend
        function onChanged() { if (!win.playing) win.seek(win.playhead) }
        function onMessage(text) { win.say(text) }
    }
    Timer { id: noteTimer; interval: 4000; onTriggered: win.note = "" }
    Timer {                                 // the playhead follows the playing deck, and the other takes over at the cut
        interval: 15; running: win.playing; repeat: true
        onTriggered: {
            const d = win.decks[win.active]
            if (!d.shot) return
            if (d.ended) { win.cut(); return }
            win.playhead = d.shot.at + Math.max(0, Math.min(d.sourceTime - d.shot.start, d.shot.duration))
        }
    }

    FileDialog {
        id: openDialog
        property bool adding: false
        title: adding ? "Add clips after the shot under the playhead" : "Open an edit or clips"
        fileMode: FileDialog.OpenFiles
        currentFolder: "file://" + (adding ? backend.libraryFolder : backend.editsFolder)
        nameFilters: adding ? ["Clips (*.MP4 *.mp4 *.MOV *.mov *.CRM)"] : ["Edits and clips (*.otio *.MP4 *.mp4 *.MOV *.mov *.CRM)"]
        onAccepted: {
            if (adding) {
                let at = win.shots.length ? win.current + 1 : 0
                for (const f of selectedFiles) backend.add(at++, f.toString())
            } else backend.open(selectedFiles.map(f => f.toString()).join("\n"))
        }
    }

    // Keys. The same keys as Omacut where the two do the same thing.
    Shortcut { sequence: "Space"; onActivated: win.playing ? win.pause() : win.play() }
    Shortcut { sequence: "Left"; onActivated: win.step(-1) }
    Shortcut { sequence: "Right"; onActivated: win.step(1) }
    Shortcut { sequence: "Shift+Left"; onActivated: win.step(-5) }
    Shortcut { sequence: "Shift+Right"; onActivated: win.step(5) }
    Shortcut { sequence: "Alt+Left"; autoRepeat: true; onActivated: win.step(-1 / (win.shots[win.current] ? win.shots[win.current].fps : 30)) }
    Shortcut { sequence: "Alt+Right"; autoRepeat: true; onActivated: win.step(1 / (win.shots[win.current] ? win.shots[win.current].fps : 30)) }
    Shortcut { sequence: "["; onActivated: win.edge(-1) }
    Shortcut { sequence: "]"; onActivated: win.edge(1) }
    Shortcut { sequence: "S"; onActivated: if (win.shots.length) backend.split(win.current, win.playhead - win.shots[win.current].at) }
    Shortcut { sequences: ["X", "Delete"]; onActivated: if (win.shots.length) backend.remove(win.current) }
    Shortcut { sequence: "Alt+["; onActivated: if (win.current > 0) backend.move(win.current, win.current - 1) }
    Shortcut { sequence: "Alt+]"; onActivated: if (win.current + 1 < win.shots.length) backend.move(win.current, win.current + 1) }
    Shortcut { sequence: "Ctrl+Space"; onActivated: { const s = win.shots[win.current]; if (s) backend.trim(win.current, win.sourceTime(win.current, win.playhead), s.start + s.duration) } }
    Shortcut { sequence: "Ctrl+Shift+Space"; onActivated: { const s = win.shots[win.current]; if (s) backend.trim(win.current, s.start, win.sourceTime(win.current, win.playhead)) } }
    Shortcut { sequences: [StandardKey.Undo]; onActivated: backend.undo() }
    Shortcut { sequences: [StandardKey.Redo, "Ctrl+Shift+Z"]; onActivated: backend.redo() }
    Shortcut { sequence: "F"; onActivated: win.framing = !win.framing && !!(win.shots[win.current] || {}).path }
    Shortcut { sequence: "R"; enabled: win.framing; onActivated: editor.turn(1) }
    Shortcut { sequence: "Shift+R"; enabled: win.framing; onActivated: editor.turn(-1) }
    Shortcut { sequence: "Escape"; enabled: win.framing; onActivated: win.framing = false }
    Shortcut { sequence: "G"; onActivated: win.graded = !win.graded }
    Shortcut { sequence: "Z"; onActivated: timeline.zoomToShot() }
    Shortcut { sequence: "Ctrl+O"; onActivated: { openDialog.adding = false; openDialog.open() } }
    Shortcut { sequence: "Ctrl+Shift+O"; onActivated: { openDialog.adding = true; openDialog.open() } }
    Shortcut { sequence: "Ctrl+R"; onActivated: backend.render() }
    Shortcut { sequence: "Q"; onActivated: Qt.quit() }
    Shortcut { sequences: ["?"]; onActivated: help.visible = !help.visible }

    component Chip: AbstractButton {
        id: chip
        property bool on: false
        implicitHeight: 30; implicitWidth: label.implicitWidth + 22
        background: Rectangle {
            radius: 6
            color: chip.on ? win.theme.accent : chip.hovered ? win.theme.selection : win.theme.raised
            opacity: chip.enabled ? 1 : 0.4
        }
        contentItem: Text {
            id: label; text: chip.text; color: chip.on ? win.theme.background : win.theme.foreground
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 13
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        // The bar: what the edit is, its aspect and look, and the render.
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { text: backend.name || "No edit open"; color: win.theme.foreground; font.pixelSize: 16; font.bold: true }
            Text { text: backend.name ? win.clock(backend.duration) : ""; color: win.theme.muted; font.pixelSize: 13 }
            Item { Layout.fillWidth: true }
            Repeater {
                model: backend.aspects
                Chip { text: modelData; on: backend.aspectName === modelData; enabled: !!backend.name; onClicked: backend.setAspect(modelData) }
            }
            Item { width: 8 }
            ComboBox {
                id: lookBox
                implicitWidth: 180; implicitHeight: 30
                model: backend.looks
                enabled: !!backend.name
                currentIndex: backend.looks.indexOf(backend.look)
                onActivated: backend.setLook(currentText)
            }
            Chip { text: "Graded"; on: win.graded; onClicked: win.graded = !win.graded }
            Chip { text: "Frame"; on: win.framing; enabled: !!(win.shots[win.current] || {}).path; onClicked: win.framing = !win.framing }
            Item { width: 8 }
            Chip { text: "Undo"; enabled: backend.canUndo; onClicked: backend.undo() }
            Chip { text: "Redo"; enabled: backend.canRedo; onClicked: backend.redo() }
            Chip {
                text: backend.progress < 0 ? "Render" : "Rendering " + Math.round(backend.progress * 100) + "%"
                on: backend.progress >= 0; enabled: !!backend.name && backend.progress < 0
                onClicked: backend.render()
            }
        }

        // The preview: the edit's frame, the playing shot drawn through its framing and printed in the look.
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            // The edit's window, fitted to the area; the frame editor opens the whole area around it.
            Item {
                id: viewport
                readonly property real fitted: Math.min(parent.width, parent.height * backend.aspect)
                readonly property real unit: win.framing ? editor.unit : fitted
                width: win.framing ? parent.width : fitted
                height: win.framing ? parent.height : fitted / backend.aspect
                anchors.centerIn: parent
                clip: true
                Rectangle { anchors.fill: parent; color: "black" }
                Deck {
                    id: deckA; anchors.fill: parent; visible: win.active === 0
                    look: backend.look; graded: win.graded; unit: viewport.unit; whole: win.framing
                    vignette: win.framing ? 0 : backend.vignette; flat: backend.flat
                    geometry: win.framing && win.active === 0 && editor.live ? editor.live.geometry : (shot ? shot.geometry : null)
                }
                Deck {
                    id: deckB; anchors.fill: parent; visible: win.active === 1
                    look: backend.look; graded: win.graded; unit: viewport.unit; whole: win.framing
                    vignette: win.framing ? 0 : backend.vignette; flat: backend.flat
                    geometry: win.framing && win.active === 1 && editor.live ? editor.live.geometry : (shot ? shot.geometry : null)
                }
                Text {                       // a title card, as the render will draw it
                    anchors.centerIn: parent
                    visible: !!(win.shots[win.current] || {}).title
                    text: (win.shots[win.current] || {}).title || ""
                    color: "white"; font.pixelSize: viewport.height * 0.045
                }

                // The frame editor: the whole turned frame, still, and the window the edit shows over it, which
                // drags and scrolls; what the window leaves out is dimmed.
                Item {
                    id: editor
                    anchors.fill: parent
                    visible: win.framing
                    readonly property var shot: win.shots[win.current] || null
                    property var live: null   // the framing being dragged, made valid by the backend
                    readonly property var g: live ? live.geometry : (shot ? shot.geometry : null)
                    // The window's width in pixels that fits the whole turned frame in the area.
                    readonly property real unit: g && g.frameWidth
                        ? Math.min(0.92 * width / g.frameWidth, 0.92 * height / g.frameHeight) : width
                    function framingNow() { return live ? live.framing : shot.framing }
                    function propose(f) { live = backend.preview(win.current, f) }
                    function commit() { if (live) backend.setFraming(win.current, live.framing); live = null }
                    function turn(by) {
                        const f = framingNow()
                        backend.setFraming(win.current, { turn: (f.turn + by + 4) % 4, center: f.center, zoom: f.zoom })
                    }
                    onShotChanged: live = null

                    readonly property real ww: unit
                    readonly property real wh: unit / backend.aspect
                    readonly property real wx: width / 2 - (g ? g.x * unit : 0) - ww / 2
                    readonly property real wy: height / 2 - (g ? g.y * unit : 0) - wh / 2
                    Rectangle { x: 0; y: 0; width: parent.width; height: editor.wy; color: "#a0000000" }
                    Rectangle { x: 0; y: editor.wy + editor.wh; width: parent.width; height: parent.height - y; color: "#a0000000" }
                    Rectangle { x: 0; y: editor.wy; width: editor.wx; height: editor.wh; color: "#a0000000" }
                    Rectangle { x: editor.wx + editor.ww; y: editor.wy; width: parent.width - x; height: editor.wh; color: "#a0000000" }
                    Rectangle {
                        x: editor.wx; y: editor.wy; width: editor.ww; height: editor.wh
                        color: "transparent"; border.color: win.theme.accent; border.width: 2
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                        property point from
                        property var start
                        onPressed: m => { from = Qt.point(m.x, m.y); start = editor.framingNow() }
                        onPositionChanged: m => {
                            if (!pressed || !editor.g) return
                            const dx = (m.x - from.x) / (editor.unit * editor.g.frameWidth)
                            const dy = (m.y - from.y) / (editor.unit * editor.g.frameHeight)
                            editor.propose({ turn: start.turn, zoom: start.zoom, center: [start.center[0] + dx, start.center[1] + dy] })
                        }
                        onReleased: editor.commit()
                        onWheel: w => {
                            const f = editor.framingNow()
                            editor.propose({ turn: f.turn, center: f.center, zoom: f.zoom * Math.pow(1.1, w.angleDelta.y / 120) })
                            commitTimer.restart()
                        }
                        Timer { id: commitTimer; interval: 400; onTriggered: editor.commit() }
                    }
                    Row {
                        anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottomMargin: 10
                        spacing: 6
                        Chip { text: "Turn left"; onClicked: editor.turn(-1) }
                        Chip { text: "Turn right"; onClicked: editor.turn(1) }
                        Chip { text: "Reset"; onClicked: backend.setFraming(win.current, {}) }
                        Chip { text: "Zoom " + (editor.shot && editor.shot.framing.zoom ? editor.framingNow().zoom.toFixed(2) + "x" : "1x"); enabled: false }
                        Chip { text: "Done"; on: true; onClicked: win.framing = false }
                    }
                }
            }
            Text {
                anchors.centerIn: parent
                visible: !backend.name
                text: "Open an edit or clips with Ctrl+O"
                color: win.theme.muted; font.pixelSize: 18
            }
        }

        // Transport.
        RowLayout {
            Layout.fillWidth: true
            Chip { text: win.playing ? "Pause" : "Play"; enabled: win.shots.length > 0; onClicked: win.playing ? win.pause() : win.play() }
            Text { text: win.clock(win.playhead) + " / " + win.clock(backend.duration); color: win.theme.foreground; font.family: "monospace" }
            Item { Layout.fillWidth: true }
            Text { text: win.note; color: win.theme.accent; elide: Text.ElideRight; Layout.maximumWidth: 700 }
            Item { Layout.fillWidth: true }
            Chip { text: "+ Add clips"; enabled: !!backend.name; onClicked: { openDialog.adding = true; openDialog.open() } }
            Chip { text: "?"; onClicked: help.visible = !help.visible }
        }

        Timeline { id: timeline; Layout.fillWidth: true; Layout.preferredHeight: 150 }
    }

    function clock(t) {
        const m = Math.floor(t / 60), s = t - m * 60
        return m + ":" + (s < 10 ? "0" : "") + s.toFixed(2)
    }

    Rectangle {
        id: help
        visible: false
        anchors.centerIn: parent
        width: 560; height: helpText.implicitHeight + 40; radius: 10
        color: win.theme.raised; border.color: win.theme.selection
        Text {
            id: helpText
            anchors.fill: parent; anchors.margins: 20
            color: win.theme.foreground; textFormat: Text.MarkdownText; wrapMode: Text.WordWrap
            text: "**Space** play or pause · **Left/Right** 1 s · **Shift** 5 s · **Alt** one frame\n\n" +
                  "**[ ]** previous or next cut · **S** split at the playhead · **X** remove the shot\n\n" +
                  "**Alt+[ ]** move the shot earlier or later · **Ctrl+Space** start the shot here · **Ctrl+Shift+Space** end it here\n\n" +
                  "**F** frame the shot: drag to move, scroll to push in, **R** turn · **G** graded or log\n\n" +
                  "**Z** zoom to the shot · **Ctrl+Z** undo · **Ctrl+Shift+Z** redo\n\n" +
                  "**Ctrl+O** open · **Ctrl+Shift+O** add clips · **Ctrl+R** render · **Q** quit\n\n" +
                  "Every change is saved to the edit file as you make it."
        }
        MouseArea { anchors.fill: parent; onClicked: help.visible = false }
    }
}
