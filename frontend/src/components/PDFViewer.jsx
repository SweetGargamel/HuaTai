import { useEffect, useRef, useState } from "react";
import { pdfjs } from "react-pdf";
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.js`;

export default function PDFViewer({ pdfUrl, highlights }) {
  const canvasRef = useRef(null);
  const [pageNum] = useState(1);

  useEffect(() => {
    if (!pdfUrl) return;
    let cancelled = false;
    pdfjs.getDocument(pdfUrl).promise.then(async (pdf) => {
      if (cancelled) return;
      const page = await pdf.getPage(pageNum);
      const viewport = page.getViewport({ scale: 1.5 });
      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");
      canvas.height = viewport.height;
      canvas.width = viewport.width;
      await page.render({ canvasContext: ctx, viewport }).promise;

      // draw highlights
      ctx.globalAlpha = 0.3;
      for (const h of highlights) {
        if (!h || !h.bbox) continue;
        const [x0, y0, x1, y1] = h.bbox;
        const color = h.confidence === "high" ? "rgba(16,185,129,0.5)" :
                      h.confidence === "medium" ? "rgba(250,204,21,0.5)" :
                      "rgba(239,68,68,0.5)";
        ctx.fillStyle = color;
        // pdf coordinates origin top-left; we need to convert Y
        ctx.fillRect(x0, viewport.height - y1, x1 - x0, y1 - y0);
      }
    }).catch((e)=> {
      console.error("Failed to load PDF:", e);
    });
    return () => { cancelled = true; };
  }, [pdfUrl, highlights, pageNum]);

  return (
    <div className="flex justify-center items-center bg-gray-50 h-full p-4">
      <canvas ref={canvasRef} className="border rounded shadow-md" />
    </div>
  );
}
