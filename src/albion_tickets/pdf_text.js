// Prints the text of the PDF named in argv[0], using macOS's own PDFKit.
// The path arrives as an argument, never in the script text.
ObjC.import('Foundation');
ObjC.import('PDFKit');

function run(argv) {
  const doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
  if (!doc || doc.isNil()) throw new Error('not a readable PDF');
  const text = doc.string;
  return text && !text.isNil() ? text.js : '';
}
