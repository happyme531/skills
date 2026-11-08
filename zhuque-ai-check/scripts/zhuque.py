#!/usr/bin/env python3
"""Archive Zhuque results and export its own browser print template; never submit detection requests."""
import argparse
import datetime as dt
import hashlib
import html
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def compact(text):
    return re.sub(r"[\s\x00-\x1f\x7f-\x9f]", "", text)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run(argv, timeout=30, input_text=None):
    p = subprocess.run(argv, input=input_text, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{argv[0]} failed: {p.stderr[:500]}")
    return p.stdout


def browser(session, *args):
    return run(["agent-browser", "--session", session, *args])


def evaluate(session, js):
    r = json.loads(run(["agent-browser", "--session", session, "eval", "--json", "--stdin"], input_text=js))
    if not r.get("success"):
        raise RuntimeError(str(r.get("error", "Browser evaluation failed"))[:500])
    return r["data"]["result"]


def entry_for(out, key):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise ValueError("Invalid input id")
    return next(x for x in load(out / "manifest.json")["inputs"] if x["id"] == key)


def prepare(args):
    out = args.out.resolve()
    if (out / "manifest.json").exists():
        raise ValueError("Manifest exists: resume it or choose a new output directory")
    if args.id and len(args.files) != 1:
        raise ValueError("--id requires exactly one input")
    entries, staged, names = [], [], set()
    for n, source in enumerate(args.files, 1):
        source = source.resolve()
        if source.suffix.lower() == ".pdf":
            text = run(["pdftotext", "-raw", str(source), "-"], timeout=120)
            method, scope = "pdftotext -raw", "all PDF pages with extractable text"
        elif source.suffix.lower() == ".txt":
            text = source.read_bytes().decode("utf-8-sig")
            method, scope = "UTF-8 TXT; optional BOM removed", "whole text file"
        elif source.suffix.lower() == ".docx":
            with zipfile.ZipFile(source) as z:
                root = ET.fromstring(z.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            tag = lambda name: f"{{{ns['w']}}}{name}"
            text = "\n".join("".join((node.text or "") if node.tag == tag("t") else "\t" if node.tag == tag("tab") else "\n" if node.tag in (tag("br"), tag("cr")) else "" for node in p.iter()) for p in root.findall(".//w:p", ns))
            method, scope = "OOXML main document paragraphs", "main document and tables; excludes headers, footnotes, endnotes"
        else:
            raise ValueError(f"Unsupported input: {source.name}")
        if not compact(text):
            raise ValueError(f"No extractable text: {source.name}; OCR or another source is needed")
        name, key = source.stem + ".txt", args.id or f"{n:02d}"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise ValueError("Invalid input id")
        if name in names or (out / "inputs" / name).exists():
            raise ValueError(f"Duplicate/existing upload name: {name}; use distinct source names")
        names.add(name)
        data = text.encode("utf-8")
        entries.append(dict(id=key, source=str(source), source_sha256=sha(source.read_bytes()), filename=name,
                            input_file=f"inputs/{name}", input_sha256=sha(data), bytes=len(data),
                            unicode_characters=len(text), utf16_code_units=len(text.encode("utf-16-le")) // 2,
                            preparation=method, scope=scope))
        staged.append((out / "inputs" / name, data))
    for path, data in staged:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    save(out / "manifest.json", dict(prepared_at=now(), inputs=entries))
    print(json.dumps({"prepared": entries}, ensure_ascii=False, indent=2))


READ_RESULT_JS = r"""(() => {
  if(location.origin !== 'https://matrix.tencent.com') throw new Error('Not the official Zhuque origin');
  const chart=Array.from(document.querySelectorAll('.pie-chart')).find(x=>x.getClientRects().length);
  const box=document.querySelector('.txt-segment-box');
  if(!chart||!box) throw new Error('No rendered text result');
  let vm=chart.__vue__,detail=null,app=null,processing=false;
  for(let i=0;vm&&i<12;i++,vm=vm.$parent){
    if(vm.processing===true)processing=true;
    if(Array.isArray(vm.segmentLabels)&&vm.segmentLabels.length)detail=vm;
    if(Array.isArray(vm.segmentLabel)&&vm.segmentLabel.length)app=vm;
  }
  if(processing)throw new Error('Processing or CAPTCHA pending; do not upload another file');
  const segments=detail?.segmentLabels||app?.segmentLabel;
  if(!segments?.length)throw new Error('Full segment data unavailable; inspect current site version');
  return {captured_at:new Date().toISOString(),source:location.href,
    filename:detail?.filename||app?.filename,
    status_label:document.querySelector('.download-link')?.parentElement.innerText.split('\n')[0].trim(),
    model_updated:document.body.innerText.match(/模型更新时间：[\s\n]*([0-9-]+)/)?.[1],
    quota_text:Array.from(document.querySelectorAll('.btn-group button')).map(x=>x.innerText).find(x=>/立即检测|今日次数已用完/.test(x)),
    confidence:detail?.aiGenerated??app?.aiGenerated,labels_ratio:chart.__vue__.labelsRatio,
    detected_text:box.textContent,
    segment_labels:segments.map(s=>({text:s.text,label:s.label,conf:s.conf,order:s.order,position:s.position}))};
})()"""


def validate(raw, source, entry):
    segments = raw.get("segment_labels")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Exact segment results missing; category colors/lengths cannot reconstruct conf")
    valid_number = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and 0 <= x <= 1
    clean = []
    for s in segments:
        if not valid_number(s.get("conf")):
            raise ValueError("Exact per-segment conf missing or invalid")
        if not isinstance(s.get("text"), str) or s.get("label") not in (0, 1, 2):
            raise ValueError("Invalid segment text or label")
        if not isinstance(s.get("order"), int) or not isinstance(s.get("position"), list) or len(s["position"]) != 2:
            raise ValueError("Original segment order/position missing")
        clean.append({k: s[k] for k in ("text", "label", "conf", "order", "position")})
    ratios = raw.get("labels_ratio", raw.get("ratios"))
    if not isinstance(ratios, dict) or set(ratios) != {"0", "1", "2"} or not all(valid_number(x) for x in ratios.values()) or abs(sum(ratios.values()) - 1) > .0003:
        raise ValueError("All three original category ratios are required and must sum to one")
    filename = raw.get("filename", raw.get("websiteFilename"))
    if filename and filename != entry["filename"]:
        raise ValueError("Website filename belongs to a different input")
    joined = "".join(s["text"] for s in clean)
    if compact(joined) != compact(raw.get("detected_text", raw.get("detectedText", joined))) or compact(joined) != compact(source):
        raise ValueError("Returned text differs from the input; inspect truncation or stale data")
    if not valid_number(raw.get("confidence")):
        raise ValueError("Original overall confidence missing; do not invent it for a report")
    return dict(id=entry["id"], filename=entry["filename"], input_file=entry["input_file"], input_sha256=entry["input_sha256"],
                captured_at=raw.get("original_capture_time", raw.get("captured_at", raw.get("capturedAt", raw.get("recoveredAt")))),
                source=raw.get("source", raw.get("url")), model_updated=raw.get("model_updated", raw.get("modelUpdated")),
                status_label=raw.get("status_label", raw.get("statusLabel")), quota_text=raw.get("quota_text", raw.get("quotaText")),
                confidence=raw["confidence"], labels_ratio=ratios, segment_labels=clean, coverage_verified=True,
                input_unicode_characters=len(source), detected_unicode_characters=len(joined))


def capture(args):
    out = args.out.resolve()
    entry = entry_for(out, args.id)
    data = (out / entry["input_file"]).read_bytes()
    if sha(data) != entry["input_sha256"]:
        raise ValueError("Prepared input changed")
    raw = load(args.from_json) if args.from_json else evaluate(args.session, READ_RESULT_JS)
    result = validate(raw, data.decode("utf-8"), entry)
    result["acquisition"] = "imported-saved-result" if args.from_json else "live-rendered-result"
    result["archived_at"] = now()
    path = out / "evidence" / f"{args.id}_result.json"
    if path.exists():
        old = load(path)
        if any(old[k] != result[k] for k in ("input_sha256", "labels_ratio", "segment_labels")):
            raise ValueError("Different result already archived; use a new output directory for a new run")
        result = old
    else:
        save(path, result)
    if not args.from_json:
        shot = out / "evidence" / f"{args.id}_result.png"
        browser(args.session, "screenshot", str(shot))
        result["screenshot"] = dict(file=str(shot.relative_to(out)), captured_at=now(), sha256=sha(shot.read_bytes()))
        save(path, result)
    print(json.dumps({"id": args.id, "coverage_verified": True, "segments": len(result["segment_labels"]),
                      "labels_ratio": result["labels_ratio"], "acquisition": result["acquisition"]}, ensure_ascii=False))


ARM_PRINT_JS = r"""(() => {
  if(location.origin!=='https://matrix.tencent.com')throw new Error('Not the official site');
  if(window.__codexZhuquePdf?.active)throw new Error('An export is already pending');
  const state=window.__codexZhuquePdf={active:true,ready:false};
  const observer=new MutationObserver(()=>{
    for(const frame of document.querySelectorAll('iframe')){
      try{
        if(!frame.contentDocument?.getElementById('report-container')||frame.__codexPrintHook)continue;
        frame.__codexPrintHook=true;
        frame.contentWindow.print=()=>{
          state.html='<!doctype html>\n'+frame.contentDocument.documentElement.outerHTML;
          state.title=frame.contentDocument.title;state.base=frame.contentDocument.baseURI;
          state.ready=true;state.active=false;observer.disconnect();
        };
      }catch(_){}
    }
  });
  state.observer=observer;observer.observe(document.body,{childList:true,subtree:true});
  const link=document.querySelector('.download-link');
  if(!link){observer.disconnect();delete window.__codexZhuquePdf;throw new Error('Report button unavailable');}
  link.click();return {armed:true};
})()"""


def export_report(args):
    out = args.out.resolve()
    entry = entry_for(out, args.id)
    path = out / "evidence" / f"{args.id}_result.json"
    result = load(path)
    source_data = (out / entry["input_file"]).read_bytes()
    if sha(source_data) != entry["input_sha256"]:
        raise ValueError("Prepared input changed")
    source_text = source_data.decode("utf-8")
    validate(result, source_text, entry)
    pdf = out / "evidence" / f"{args.id}_report.pdf"
    if result.get("pdf", {}).get("verified") and result["pdf"].get("checks", {}).get("stylesheets_loaded") and pdf.exists() and sha(pdf.read_bytes()) == result["pdf"]["sha256"]:
        print(json.dumps({"id": args.id, "pdf": str(pdf), "cached": True})); return
    if pdf.exists():
        raise ValueError("Unverified PDF exists; inspect it or choose a new output directory")
    if args.restore:
        payload = {k: result[k] for k in ("filename", "confidence", "labels_ratio", "segment_labels")}
        js = """(()=>{if(location.origin!=='https://matrix.tencent.com')throw new Error('Wrong origin');
        let v=document.querySelector('.pie-chart')?.__vue__,app=null;
        for(let i=0;v&&i<12;i++,v=v.$parent)if(Array.isArray(v.segmentLabel)&&v.data)app=v;
        if(!app||app.processing)throw new Error('No idle result view');const d=PAYLOAD;
        app.data={...app.data,status:'success',confidence:d.confidence,labels_ratio:d.labels_ratio,segment_labels:d.segment_labels};
        app.aiGenerated=d.confidence;app.segmentLabel=d.segment_labels;app.filename=d.filename;
        return {restored:true,scope:'display only; account quota retained'};})()""".replace("PAYLOAD", json.dumps(payload, ensure_ascii=False))
        evaluate(args.session, js)
        time.sleep(.2)
    current = validate(evaluate(args.session, READ_RESULT_JS), source_text, entry)
    if any(current[k] != result[k] for k in ("labels_ratio", "segment_labels")):
        raise ValueError("Current displayed result differs from archive")
    shot = out / "evidence" / f"{args.id}_result.png"
    browser(args.session, "screenshot", str(shot))
    result["screenshot"] = dict(file=str(shot.relative_to(out)), captured_at=now(), restored_from_archive=args.restore,
                                sha256=sha(shot.read_bytes()))
    save(path, result)
    evaluate(args.session, ARM_PRINT_JS)
    ready = False
    for _ in range(40):
        if evaluate(args.session, "({ready:!!window.__codexZhuquePdf?.ready})")["ready"]:
            ready = True; break
        time.sleep(.25)
    if not ready:
        evaluate(args.session, "(()=>{window.__codexZhuquePdf?.observer?.disconnect();delete window.__codexZhuquePdf;return true})()")
        raise RuntimeError("Report iframe not captured; inspect any native print window before retrying")
    document = evaluate(args.session, "({html:window.__codexZhuquePdf.html,title:window.__codexZhuquePdf.title,base:window.__codexZhuquePdf.base})")
    report_html = pdf.with_suffix(".html")
    source_html = pdf.with_name(pdf.stem + "_source.html")
    source_html.write_text(document["html"], encoding="utf-8")
    # A file:// copy needs the original base URL for the website's relative CSS links.
    portable = document["html"].replace("<head>", '<head><base href="' + html.escape(document["base"], quote=True) + '">', 1)
    report_html.write_text(portable, encoding="utf-8")
    evaluate(args.session, "(()=>{delete window.__codexZhuquePdf;return true})()")
    browser(args.session, "tab", "new", report_html.as_uri())
    try:
        if browser(args.session, "get", "url").strip() != report_html.as_uri():
            raise RuntimeError("Report tab not selected; stop to avoid printing another page")
        resources = evaluate(args.session, "(async()=>{await document.fonts.ready;const links=Array.from(document.querySelectorAll('link[rel=stylesheet]'));return {stylesheets_loaded:links.length>0&&links.every(x=>!!x.sheet)}})()")
        if not resources["stylesheets_loaded"]:
            raise RuntimeError("Official report CSS did not load; stop before producing an unstyled PDF")
        browser(args.session, "pdf", str(pdf))
    finally:
        if browser(args.session, "get", "url").strip() == report_html.as_uri():
            browser(args.session, "tab", "close")
    info = run(["pdfinfo", str(pdf)])
    pages = int(re.search(r"^Pages:\s+(\d+)", info, re.M).group(1))
    text = run(["pdftotext", "-raw", str(pdf), "-"], timeout=60)
    checks = dict(filename=compact(entry["filename"]) in compact(text),
                  all_segment_confidences=all(f"{s['conf']:.4f}" in text for s in result["segment_labels"]),
                  all_segment_texts=all(compact(s["text"]) in compact(text) for s in result["segment_labels"]),
                  text_tail=compact(result["segment_labels"][-1]["text"])[-60:] in compact(text), **resources)
    result["pdf"] = dict(file=str(pdf.relative_to(out)), html=str(report_html.relative_to(out)), source_html=str(source_html.relative_to(out)),
                         exported_at=now(), restored_from_archive=args.restore, pages=pages,
                         sha256=sha(pdf.read_bytes()), checks=checks, verified=pages > 0 and all(checks.values()))
    save(path, result)
    if not result["pdf"]["verified"]:
        raise RuntimeError(f"PDF retained but verification failed: {checks}; inspect source template and PDF")
    print(json.dumps({"id": args.id, "pdf": result["pdf"]}, ensure_ascii=False, indent=2))


def summary(args):
    out = args.out.resolve()
    rows = []
    for entry in load(out / "manifest.json")["inputs"]:
        p = out / "evidence" / f"{entry['id']}_result.json"
        r = load(p) if p.exists() else None
        row = dict(id=entry["id"], filename=entry["filename"], input_sha256=entry["input_sha256"], scope=entry["scope"], state="pending")
        if r:
            source = (out / entry["input_file"]).read_bytes()
            if sha(source) != entry["input_sha256"]:
                raise ValueError(f"Prepared input changed: {entry['id']}")
            validate(r, source.decode("utf-8"), entry)
            pdf_meta = r.get("pdf", {})
            pdf_path = out / pdf_meta.get("file", "missing.pdf")
            pdf_ok = pdf_meta.get("verified") and pdf_path.is_file() and sha(pdf_path.read_bytes()) == pdf_meta.get("sha256")
            shot = out / "evidence" / f"{entry['id']}_result.png"
            shot_ok = shot.is_file() and (not r.get("screenshot", {}).get("sha256") or sha(shot.read_bytes()) == r["screenshot"]["sha256"])
            row.update(state="complete" if pdf_ok and shot_ok else "awaiting-pdf" if not pdf_ok else "awaiting-screenshot", ratios=r["labels_ratio"],
                       captured_at=r["captured_at"], model_updated=r.get("model_updated"), coverage_verified=r["coverage_verified"],
                       raw=str(p.relative_to(out)), pdf=r.get("pdf"))
        rows.append(row)
    save(out / "summary.json", dict(generated_at=now(), results=rows))
    esc = lambda x: html.escape(str(x), quote=True)
    body = []
    for r in rows:
        ratio = r.get("ratios", {})
        metrics = "".join(f"<td>{100*ratio[k]:.2f}%</td>" if k in ratio else "<td>—</td>" for k in ("0", "2", "1"))
        links = f'<a href="{esc(r["raw"])}">完整结果</a>' if r.get("raw") else ""
        if r.get("pdf"): links += f' · <a href="{esc(r["pdf"]["file"])}">PDF</a>'
        shot = f'evidence/{r["id"]}_result.png'
        if (out / shot).exists(): links += f' · <a href="{shot}">截图</a>'
        body.append(f'<tr><td>{esc(r["filename"])}</td><td>{r["state"]}</td>{metrics}<td>{links}</td></tr>')
    page = '<!doctype html><meta charset="utf-8"><title>朱雀检测记录</title><style>body{font:16px/1.8 sans-serif;max-width:1200px;margin:32px auto;padding:20px}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}a{color:#165aab}</style><h1>朱雀检测记录</h1><p>占比为检测器分类结果；输入范围见 manifest.json。complete 表示完整分段数据、全文核对、截图及 PDF 校验通过。</p><table><tr><th>文件</th><th>状态</th><th>人工特征</th><th>疑似AI</th><th>AI特征</th><th>记录</th></tr>'+''.join(body)+'</table>'
    (out / "index.html").write_text(page, encoding="utf-8")
    print(json.dumps({"index": str(out / "index.html"), "states": {r["id"]: r["state"] for r in rows}}, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="command", required=True)
    for name in ("prepare", "capture", "export", "summary"):
        cmd = subs.add_parser(name); cmd.add_argument("--out", type=Path, required=True)
        if name == "prepare": cmd.add_argument("files", nargs="+", type=Path); cmd.add_argument("--id")
        if name in ("capture", "export"): cmd.add_argument("--id", required=True); cmd.add_argument("--session", default="zhuque")
        if name == "capture": cmd.add_argument("--from-json", type=Path)
        if name == "export": cmd.add_argument("--restore", action="store_true")
    args = p.parse_args()
    try:
        {"prepare": prepare, "capture": capture, "export": export_report, "summary": summary}[args.command](args)
    except (ValueError, RuntimeError, KeyError, StopIteration, OSError, subprocess.TimeoutExpired) as e:
        print(f"ERROR: {e}", file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
