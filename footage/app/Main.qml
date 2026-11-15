// Azimuth Video: cut, trim and frame an edit. Everything shown is computed from backend.shots, which the backend
// recomputes from the edit after every change; the window only keeps the playhead, what is playing, and drags.
// It draws only with the Azimuth design system (import Azimuth as Az: the kit vendored in azimuth/qml): colours,
// type, sizes, corners, motion and icons all come from it, so a design change reaches the app by re-vendoring.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import Azimuth as Az

ApplicationWindow {
    id: win
    width: 1600; height: 1000
    visible: true
    title: backend.name ? backend.name + " — Azimuth Video" : "Azimuth Video"
    color: Az.Theme.canvas

    readonly property var shots: backend.shots
    property real playhead: 0
    property bool playing: false
    property bool framing: false          // the frame editor is open on the shot under the playhead
    property bool graded: true
    property int active: 0                // which deck plays
    readonly property var decks: [deckA, deckB]
    readonly property int current: locate(playhead)
    readonly property real fps: (shots[current] || {}).fps || 30

    font: Az.Theme.fonts.body
    palette.window: Az.Theme.canvas; palette.windowText: Az.Theme.text
    palette.base: Az.Theme.well; palette.text: Az.Theme.text
    palette.highlight: Az.Theme.selection; palette.highlightedText: Az.Theme.text

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
    function frames(n) { step(n / fps) }
    function edge(direction) {
        const edges = shots.map(s => s.at).concat([backend.duration])
        const next = direction > 0 ? edges.find(e => e > playhead + 0.01) : edges.slice().reverse().find(e => e < playhead - 0.01)
        if (next !== undefined) step(next - playhead)
    }
    // [ and ]: the shot under the playhead starts or ends here.
    function trimHere(end) {
        const s = shots[current]
        if (!s) return
        if (end === "in") backend.trim(current, sourceTime(current, playhead), s.start + s.duration)
        else backend.trim(current, s.start, sourceTime(current, playhead))
    }
    function say(text) { toast.show(text) }
    // Esc backs out one level: the key sheet, the frame editor, the preview's zoom.
    function back() {
        if (help.opened) help.close()
        else if (framing) editor.cancel()
        else if (viewer.mode !== "fit") viewer.zoomTo("fit")
        else if (win.visibility === Window.FullScreen) win.showNormal()
    }

    Connections {
        target: backend
        function onChanged() { if (!win.playing) win.seek(win.playhead) }
        function onMessage(text) { win.say(text) }
    }
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
    function openEdit() { openDialog.adding = false; openDialog.open() }
    function addClips() { openDialog.adding = true; openDialog.open() }

    // Keys: the Azimuth keymap (the same key, the same verb, in every app), and Video's own where the map has none.
    Shortcut { sequence: "Space"; onActivated: win.playing ? win.pause() : win.play() }
    Shortcut { sequence: "Left"; autoRepeat: true; onActivated: win.frames(-1) }
    Shortcut { sequence: "Right"; autoRepeat: true; onActivated: win.frames(1) }
    Shortcut { sequence: "Shift+Left"; autoRepeat: true; onActivated: win.frames(-10) }
    Shortcut { sequence: "Shift+Right"; autoRepeat: true; onActivated: win.frames(10) }
    Shortcut { sequence: "Alt+Left"; autoRepeat: true; onActivated: win.step(-1) }
    Shortcut { sequence: "Alt+Right"; autoRepeat: true; onActivated: win.step(1) }
    Shortcut { sequence: "Up"; onActivated: win.edge(-1) }
    Shortcut { sequence: "Down"; onActivated: win.edge(1) }
    Shortcut { sequence: "["; onActivated: win.framing ? editor.turn(-1) : win.trimHere("in") }
    Shortcut { sequence: "]"; onActivated: win.framing ? editor.turn(1) : win.trimHere("out") }
    Shortcut { sequence: "S"; onActivated: if (win.shots.length) backend.split(win.current, win.playhead - win.shots[win.current].at) }
    Shortcut { sequences: ["X", "Delete"]; onActivated: if (win.shots.length) backend.remove(win.current) }
    Shortcut { sequence: "Alt+["; onActivated: if (win.current > 0) backend.move(win.current, win.current - 1) }
    Shortcut { sequence: "Alt+]"; onActivated: if (win.current + 1 < win.shots.length) backend.move(win.current, win.current + 1) }
    Shortcut { sequences: [StandardKey.Undo]; onActivated: backend.undo() }
    Shortcut { sequences: [StandardKey.Redo, "Ctrl+Shift+Z"]; onActivated: backend.redo() }
    Shortcut { sequence: "R"; onActivated: win.framing ? editor.apply() : editor.open() }
    Shortcut { sequences: ["Return", "Enter"]; enabled: win.framing && !help.opened; onActivated: editor.apply() }
    Shortcut { sequence: "Escape"; enabled: !help.opened; onActivated: win.back() }
    Shortcut { sequence: "\\"; onActivated: win.graded = !win.graded }
    Shortcut { sequence: "Z"; onActivated: timeline.zoomToShot() }
    Shortcut { sequence: "F"; onActivated: win.visibility === Window.FullScreen ? win.showNormal() : win.showFullScreen() }
    Shortcut { sequence: "Ctrl+O"; onActivated: win.openEdit() }
    Shortcut { sequence: "Ctrl+Shift+O"; onActivated: win.addClips() }
    Shortcut { sequence: "Ctrl+E"; onActivated: backend.render() }
    Shortcut { sequence: "Q"; onActivated: Qt.quit() }
    Shortcut { sequences: ["?", "Shift+?"]; onActivated: help.opened ? help.close() : help.open() }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // The bar: the brand, what the edit is, its look and toggles, undo, the theme, and the render.
        Az.TopBar {
            id: topBar
            Layout.fillWidth: true
            tag: "Video"
            Az.Label {
                textStyle: "title"
                text: backend.name || "No edit open"
                color: backend.name ? Az.Theme.text : Az.Theme.text3
                Layout.maximumWidth: 360
            }
            Az.Timecode { visible: !!backend.name; seconds: backend.duration; fps: win.fps; faint: true }
            Item { Layout.fillWidth: true }
            Az.Select {
                id: lookBox
                implicitWidth: 170
                model: backend.looks
                enabled: !!backend.name
                currentIndex: backend.looks.indexOf(backend.look)
                onActivated: i => backend.setLook(backend.looks[i])
                Az.Tip { text: "Look"; visible: lookBox.hovered && !lookBox.popup.visible }
            }
            Az.Button { text: "Graded"; checkable: true; checked: win.graded; onToggled: win.graded = checked; tip: "Graded or log · \\" }
            Az.Button {
                text: "Frame"; icon.name: "crop"; checkable: true; checked: win.framing
                enabled: !!(win.shots[win.current] || {}).path
                onToggled: checked ? editor.open() : editor.apply()
                tip: "Frame the shot · R"
            }
            Item { implicitWidth: 4 }
            Az.Button { icon.name: "undo"; enabled: backend.canUndo; onClicked: backend.undo(); tip: "Undo · Ctrl+Z" }
            Az.Button { icon.name: "redo"; enabled: backend.canRedo; onClicked: backend.redo(); tip: "Redo · Ctrl+Shift+Z" }
            Item { implicitWidth: 4 }
            Az.Select {
                id: themeBox
                implicitWidth: 190
                model: Az.Theme.choices.map(c => c.name)
                currentIndex: Az.Theme.choices.findIndex(c => c.id === Az.Theme.choice)
                onActivated: i => Az.Theme.choose(Az.Theme.choices[i].id)
                Az.Tip { text: "Theme"; visible: themeBox.hovered && !themeBox.popup.visible }
            }
            Az.Button {
                kind: "go"
                icon.name: "render"
                busy: backend.progress >= 0
                text: busy ? "Rendering " + Math.round(backend.progress * 100) + "%" : "Render"
                enabled: !!backend.name
                onClicked: if (!busy) backend.render()
                tip: busy ? "" : "Render · Ctrl+E"
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: Az.Theme.size.gutter
            spacing: Az.Theme.size.gutter

            // The viewer: the edit's frame on the stage, the playing shot drawn through its framing and printed in
            // the look, then the transport.
            Az.Panel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                Rectangle {
                    id: stage
                    x: 1; y: 1
                    width: parent.width - 2
                    height: parent.height - 2 - transport.height
                    color: Az.Theme.stage
                    clip: true

                    // The preview's zoom: fit, fill, 1:1 and 2:1 of the render's pixels, or free from the wheel;
                    // pan is the window's offset from the stage's centre.
                    Item {
                        id: viewer
                        anchors.fill: parent
                        property string mode: "fit"
                        property real free: 0
                        property point pan: Qt.point(0, 0)
                        readonly property real dpr: Screen.devicePixelRatio || 1
                        readonly property real fit: Math.min(width, height * backend.aspect)
                        readonly property real pixel: backend.masterWidth > 0 ? backend.masterWidth / dpr : fit
                        readonly property real unit: mode === "fit" ? fit : mode === "fill" ? Math.max(width, height * backend.aspect)
                                                   : mode === "1:1" ? pixel : mode === "2:1" ? 2 * pixel : free
                        readonly property real percent: backend.masterWidth > 0 ? 100 * unit * dpr / backend.masterWidth : 100
                        function clampPan(p, u) {
                            const mx = Math.max(0, (u - width) / 2), my = Math.max(0, (u / backend.aspect - height) / 2)
                            return Qt.point(Math.max(-mx, Math.min(mx, p.x)), Math.max(-my, Math.min(my, p.y)))
                        }
                        // Zoom to a mode or a width, keeping the point (x, y) of the stage where it is.
                        function zoomTo(m, u, x, y) {
                            const before = unit
                            const ax = x === undefined ? width / 2 : x, ay = y === undefined ? height / 2 : y
                            if (m === "") free = u
                            mode = m
                            const k = unit / before
                            const cx = width / 2 + pan.x, cy = height / 2 + pan.y
                            pan = m === "fit" ? Qt.point(0, 0) : clampPan(Qt.point(ax + (cx - ax) * k - width / 2, ay + (cy - ay) * k - height / 2), unit)
                        }
                        function toggle(x, y) { zoomTo(mode === "fit" ? "1:1" : "fit", 0, x, y) }
                        onWidthChanged: pan = clampPan(pan, unit)
                        onHeightChanged: pan = clampPan(pan, unit)

                        MouseArea {                  // double-click toggles Fit and 1:1 at the point; wheel zooms; drag pans
                            anchors.fill: parent
                            enabled: !win.framing && !!backend.name
                            cursorShape: viewer.unit > viewer.fit + 1 ? (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor) : Qt.ArrowCursor
                            property point from
                            property point start
                            onPressed: m => { from = Qt.point(m.x, m.y); start = viewer.pan }
                            onPositionChanged: m => { if (pressed) viewer.pan = viewer.clampPan(Qt.point(start.x + m.x - from.x, start.y + m.y - from.y), viewer.unit) }
                            onDoubleClicked: m => viewer.toggle(m.x, m.y)
                            onWheel: w => viewer.zoomTo("", Math.max(viewer.fit * 0.25, Math.min(viewer.pixel * 8, viewer.unit * Math.pow(1.15, w.angleDelta.y / 120))), w.x, w.y)
                        }
                    }

                    // The edit's window on the stage; the frame editor opens the whole stage around it.
                    Item {
                        id: viewport
                        readonly property real unit: win.framing ? editor.unit : viewer.unit
                        width: win.framing ? parent.width : unit
                        height: win.framing ? parent.height : unit / backend.aspect
                        x: (parent.width - width) / 2 + (win.framing ? 0 : viewer.pan.x)
                        y: (parent.height - height) / 2 + (win.framing ? 0 : viewer.pan.y)
                        visible: !!backend.name
                        clip: true
                        Rectangle { anchors.fill: parent; visible: !win.framing; color: "black" }  // az-lint: allow: the render's own black under the picture
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
                            color: "white"  // az-lint: allow: drawn as the render draws a title card
                            font.family: Az.Theme.fontSans
                            font.pixelSize: Math.max(1, viewport.height * 0.045)
                        }
                    }

                    // The frame editor: the whole turned frame, still, and the window the edit shows over it, in the
                    // shared frame overlay. Drag inside pans, the wheel and the handles push in, [ ] turn.
                    Az.FrameOverlay {
                        id: editor
                        anchors.fill: parent
                        visible: win.framing
                        readonly property var shot: win.shots[win.current] || null
                        property var live: null          // the framing being dragged, made valid by the backend
                        property var before: null        // the framing when the editor opened, for Cancel
                        property int index: -1
                        readonly property var g: live ? live.geometry : (shot ? shot.geometry : null)
                        // The window's width in pixels that fits the whole turned frame in the stage.
                        readonly property real unit: g && g.frameWidth
                            ? Math.min(0.92 * width / g.frameWidth, 0.82 * height / g.frameHeight) : width
                        readonly property real ww: unit
                        readonly property real wh: unit / backend.aspect
                        frame: Qt.rect(width / 2 - (g ? g.x * unit : 0) - ww / 2, height / 2 - (g ? g.y * unit : 0) - wh / 2, ww, wh)
                        dragging: framePan.pressed

                        function framingNow() { return live ? live.framing : shot.framing }
                        function propose(f) { live = backend.preview(win.current, f) }
                        function commit() { if (live) backend.setFraming(win.current, live.framing); live = null }
                        function turn(by) {
                            const f = framingNow()
                            backend.setFraming(win.current, { turn: (f.turn + by + 4) % 4, center: f.center, zoom: f.zoom })
                        }
                        function open() {
                            if (!(shot && shot.path)) return
                            before = JSON.parse(JSON.stringify(shot.framing)); index = win.current; win.framing = true
                        }
                        function apply() { commit(); win.framing = false }
                        function cancel() {
                            live = null
                            if (before && index === win.current && JSON.stringify(before) !== JSON.stringify(shot.framing))
                                backend.setFraming(index, before)
                            win.framing = false
                        }
                        onShotChanged: live = null

                        // A handle drag pushes in or out about the centre: the window's new width sets the zoom.
                        property real startWidth: 0
                        property var startFraming: null
                        onHandleStarted: { startWidth = ww; startFraming = framingNow() }
                        onHandleMoved: (name, dx, dy) => {
                            const across = (name.indexOf("e") >= 0 ? dx : name.indexOf("w") >= 0 ? -dx : 0) * 2
                            const down = (name.indexOf("s") >= 0 ? dy : name.indexOf("n") >= 0 ? -dy : 0) * 2 * backend.aspect
                            const grow = Math.abs(across) > Math.abs(down) ? across : down
                            const w = Math.max(16, startWidth + grow)
                            propose({ turn: startFraming.turn, center: startFraming.center, zoom: startFraming.zoom * startWidth / w })
                        }
                        onHandleEnded: commit()

                        MouseArea {
                            id: framePan
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
                                editor.propose({ turn: f.turn, center: f.center, zoom: f.zoom * Math.pow(1.15, w.angleDelta.y / 120) })
                                commitTimer.restart()
                            }
                            Timer { id: commitTimer; interval: 400; onTriggered: editor.commit() }
                        }

                        bar: [
                            Az.Button { small: true; icon.name: "rotate-left"; tip: "Turn left · ["; onClicked: editor.turn(-1) },
                            Az.Button { small: true; icon.name: "rotate-right"; tip: "Turn right · ]"; onClicked: editor.turn(1) },
                            Az.Label {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 64; horizontalAlignment: Text.AlignHCenter
                                textStyle: "code"; color: Az.Theme.text2
                                text: editor.shot && editor.shot.framing ? editor.framingNow().zoom.toFixed(2) + "×" : ""
                            },
                            Az.Button { small: true; text: "Reset"; onClicked: backend.setFraming(win.current, {}) },
                            Az.Button { small: true; kind: "bare"; key: "Esc"; text: "Cancel"; onClicked: editor.cancel() },
                            Az.Button { small: true; kind: "primary"; key: "⏎"; text: "Apply"; onClicked: editor.apply() }
                        ]
                    }

                    Az.EmptyState {
                        anchors.centerIn: parent
                        visible: !backend.name
                        title: "Open an edit"
                        text: "Open an edit, or clips to start a new one. Every change is saved to the edit as you make it."
                        action: "Open"
                        actionIcon: "open"
                        onActivated: win.openEdit()
                    }

                    Az.ZoomChip {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 12
                        visible: !!backend.name && !win.framing
                        mode: viewer.mode
                        percent: viewer.percent
                        onPicked: m => viewer.zoomTo(m)
                    }

                    Az.Toast { id: toast; bottomMargin: backend.name ? 56 : 14 }
                }

                // Transport: step and play, where the playhead is, the edit's aspect, and the edit's verbs.
                Item {
                    id: transport
                    anchors.bottom: parent.bottom
                    x: 1; width: parent.width - 2
                    height: 44
                    Rectangle { width: parent.width; height: 1; color: Az.Theme.line }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12; anchors.rightMargin: 12
                        spacing: 10
                        Az.Segmented {
                            enabled: win.shots.length > 0
                            currentIndex: -1
                            model: [{ icon: "step-back", tip: "Previous cut · ↑" },
                                    { icon: win.playing ? "pause" : "play", tip: (win.playing ? "Pause" : "Play") + " · Space" },
                                    { icon: "step-forward", tip: "Next cut · ↓" }]
                            onActivated: i => i === 1 ? (win.playing ? win.pause() : win.play()) : win.edge(i === 0 ? -1 : 1)
                        }
                        Az.Timecode { seconds: win.playhead; fps: win.fps }
                        Az.Label { textStyle: "label"; color: Az.Theme.text3; text: "/" }
                        Az.Timecode { seconds: backend.duration; fps: win.fps; faint: true }
                        Item { Layout.fillWidth: true }
                        Az.Segmented {
                            small: true
                            enabled: !!backend.name
                            model: backend.aspects
                            currentIndex: backend.aspects.indexOf(backend.aspectName)
                            onActivated: i => backend.setAspect(backend.aspects[i])
                        }
                        Az.Button {
                            small: true; icon.name: "split"; tip: "Split at the playhead · S"
                            enabled: win.shots.length > 0
                            onClicked: backend.split(win.current, win.playhead - win.shots[win.current].at)
                        }
                        Az.Button { small: true; icon.name: "plus"; text: "Add clips"; enabled: !!backend.name; onClicked: win.addClips() }
                        Az.Button { small: true; icon.name: "keyboard"; tip: "Keys · ?"; onClicked: help.open() }
                    }
                }
            }

            Az.Panel {
                Layout.fillWidth: true
                Layout.preferredHeight: 150
                Timeline { id: timeline; anchors.fill: parent; anchors.margins: 1 }
            }
        }
    }

    // The key sheet.
    Az.Dialog {
        id: help
        eyebrow: "Keys"
        title: "Cut, trim and frame"
        readonly property var keys: [
            [["Space"], "Play or pause"],
            [["←", "→"], "One frame; with Shift, ten; with Alt, a second"],
            [["↑", "↓"], "The previous or next cut"],
            [["[", "]"], "The shot starts or ends at the playhead"],
            [["S"], "Split the shot at the playhead"],
            [["X"], "Remove the shot"],
            [["Alt", "[", "]"], "Move the shot earlier or later"],
            [["R"], "Frame the shot: drag, scroll or pull a handle; [ ] turn; ⏎ apply; Esc cancel"],
            [["\\"], "Graded or log"],
            [["Z"], "Fit the timeline to the shot"],
            [["F"], "Full screen"],
            [["Ctrl", "Z"], "Undo; with Shift, redo"],
            [["Ctrl", "O"], "Open; with Shift, add clips"],
            [["Ctrl", "E"], "Render"],
            [["Q"], "Quit"]
        ]
        Repeater {
            model: help.keys
            Row {
                required property var modelData
                spacing: 12
                Row {
                    width: 96
                    spacing: 4
                    Repeater { model: modelData[0]; Az.KeyCap { required property string modelData; text: modelData } }
                }
                Az.Label { text: modelData[1]; width: 380; wrapMode: Text.Wrap; elide: Text.ElideNone }
            }
        }
        Az.Label { textStyle: "meta"; color: Az.Theme.text3; text: "Every change is saved to the edit as you make it. Double-click the picture to see it at 1:1." }
        actions: [ Az.Button { kind: "primary"; text: "Done"; onClicked: help.close() } ]
    }
}
