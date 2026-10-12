import { useState } from "react";
import type { ShareKit as Kit } from "../features";
export function ShareKit({ kit, demo }: { kit?: Kit; demo: boolean }) {
  const [message, setMessage] = useState("");
  async function copy(label: string, text: string) {
    try { await navigator.clipboard.writeText(text); setMessage(`${label} copied`); }
    catch { setMessage("Clipboard unavailable. Select and copy the text below."); }
  }
  return <section className="panel share-kit" aria-label="Share kit">
    <h2>Share kit</h2>
    {!kit ? <p>No share kit supplied. Enable Share kit before rendering on a supported backend.</p> : <>
      {demo && <p className="hint">Demo cover and posting copy. Video and asset downloads require a real render.</p>}
      <div className="cover-grid">{kit.thumbnails.map((t, i) => <figure key={i}>
        <img src={t.url} alt={t.label} /><figcaption>{t.label}</figcaption>
        {!demo && <a href={t.url} download>Download {t.label}</a>}
      </figure>)}</div>
      {!kit.thumbnails.length && <p>No thumbnails supplied.</p>}
      <h3>Title ideas</h3>
      {kit.titles.map((title, i) => <div className="copy-row" key={i}><p>{title}</p><button onClick={() => void copy(`Title ${i + 1}`, title)}>Copy title {i + 1}</button></div>)}
      {([ ["Description", kit.description], ["Chapters", kit.chapters] ] as const).map(([label, value]) => <div key={label}>
        <label>{label}<textarea readOnly value={value} rows={4} /></label>
        <button disabled={!value} onClick={() => void copy(label, value)}>Copy {label.toLowerCase()}</button>
      </div>)}
      {!demo && <div className="asset-downloads">{kit.downloads.map((d, i) => <a key={i} href={d.url} download>{d.label}</a>)}</div>}
      <p role="status">{message}</p>
    </>}
  </section>;
}
