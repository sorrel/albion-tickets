// Reads one JSON request on stdin and acts on Calendar.app. Prints a result line.
// Data never goes into the script text, so titles can't break or inject anything.
ObjC.import('Foundation');

function readStdin() {
  const data = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
  return $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding).js;
}

function findCalendar(app, name) {
  const found = app.calendars.whose({ name: name })();
  return found.length ? found[0] : null;
}

function findEvent(cal, uid) {
  if (!uid) return null;
  const found = cal.events.whose({ uid: uid })();
  return found.length ? found[0] : null;
}

function run() {
  const req = JSON.parse(readStdin());
  const app = Application('Calendar');
  const cal = findCalendar(app, req.calendar);
  if (!cal) return 'missing';
  if (req.op === 'check') return 'ok';

  if (req.op === 'remove') {
    const ev = findEvent(cal, req.uid);
    if (ev) app.delete(ev);
    return 'removed';
  }

  // upsert
  let ev = findEvent(cal, req.uid);
  if (!ev) {
    ev = app.Event({ summary: req.title, startDate: new Date(req.start), endDate: new Date(req.end) });
    cal.events.push(ev);
  }
  ev.summary = req.title;
  ev.startDate = new Date(req.start);
  ev.endDate = new Date(req.end);
  ev.description = req.notes;
  const old = ev.displayAlarms();
  for (let i = old.length - 1; i >= 0; i--) app.delete(old[i]);
  req.alarms.forEach(function (mins) {
    ev.displayAlarms.push(app.DisplayAlarm({ triggerInterval: mins }));
  });
  return ev.uid();
}
