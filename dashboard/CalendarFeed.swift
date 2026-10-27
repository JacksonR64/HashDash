import AppKit
import EventKit
import Foundation
import Darwin

// A one-shot app gives Calendar a stable permission identity; it never edits events.
umask(0o077)
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let store = EKEventStore()
let folder = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/ConsoleDashboard")
let iso = ISO8601DateFormatter()

func finish(_ granted: Bool) {
    defer { app.terminate(nil) }
    do {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let access = try JSONSerialization.data(withJSONObject: ["granted": granted, "checked_at": iso.string(from: Date())])
        try access.write(to: folder.appendingPathComponent("calendar-access.json"), options: .atomic)
        guard granted else { return }
        let now = Date()
        let predicate = store.predicateForEvents(withStart: now.addingTimeInterval(-86400), end: now.addingTimeInterval(45 * 86400), calendars: nil)
        let events: [[String: Any]] = store.events(matching: predicate).map { event in
            ["title": event.title ?? "", "start": iso.string(from: event.startDate),
             "end": iso.string(from: event.isAllDay ? event.endDate.addingTimeInterval(-1) : event.endDate),
             "calendar": event.calendar.title, "allday": event.isAllDay]
        }
        let data = try JSONSerialization.data(withJSONObject: ["updated_at": iso.string(from: now), "events": events])
        try data.write(to: folder.appendingPathComponent("calendar-feed.json"), options: .atomic)
    } catch {
        // Retain the previous successful feed, with its original freshness timestamp.
    }
}

store.requestFullAccessToEvents { granted, _ in
    DispatchQueue.main.async { finish(granted) }
}
app.run()
