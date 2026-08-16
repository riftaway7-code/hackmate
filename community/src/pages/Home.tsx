import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchCategories } from '../lib/queries'
import type { Category } from '../lib/types'

const features = [
  'Scans CPU, GPU, audio, ethernet, Wi-Fi, NVMe, and Thunderbolt',
  'Shows compatible macOS versions for your hardware',
  'Formats USB and downloads macOS Recovery directly from Apple',
  'Generates SMBIOS, config.plist, SSDTs, and kexts automatically',
  'Includes a config.plist editor with framebuffer and audio suggestions',
  'Uses the same trusted tools as the Dortania guide',
]

const faqs = [
  ['Is it safe to run?', 'HackMate only touches the target USB drive. Internal disks are hidden from the device list, and the source is fully open on GitHub.'],
  ['Why did antivirus flag the EXE?', 'PyInstaller applications can trigger heuristic scanners. The Windows build is produced transparently from this repository by GitHub Actions.'],
  ['Do I still need the Dortania guide?', 'HackMate automates the guide workflow with tools such as macrecovery, SSDTTime, and OpenCore. The guide is still useful for learning how everything works.'],
  ['Does it download the full offline installer?', 'Not currently. It downloads Apple’s recovery image, which retrieves the full macOS payload after booting.'],
]

export function Home() {
  const [categories, setCategories] = useState<Category[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [downloads, setDownloads] = useState<number | null>(null)

  useEffect(() => {
    fetchCategories().then(setCategories).catch((caught) => setError(caught.message))
    fetch(`${import.meta.env.BASE_URL}stats.json`).then((response) => response.json()).then((data) => setDownloads(data.total_downloads ?? 0)).catch(() => undefined)
  }, [])

  return (
    <div>
      <div className="home-grid">
        <div>
          <section className="hero">
            <div className="eyebrow">Open source · community powered</div>
            <h1>Build better Hackintoshes, together.</h1>
            <p>HackMate automates the OpenCore USB process. Get the app, ask for help, report issues, and share what worked.</p>
            <div className="hero-actions"><a className="primary-link" href="https://github.com/riftaway7-code/hackmate/releases/latest">Download for Windows</a><a className="text-link" href="https://github.com/riftaway7-code/hackmate">View on GitHub ↗</a></div>
          </section>
          <div className="section-title">Browse channels</div>
          {error && <div className="error">{error}</div>}
          {!categories && !error && <div className="meta">Loading channels…</div>}
          <div className="category-grid">{categories?.map((category) => (
            <Link key={category.id} to={`/c/${category.slug}`}><article className="category-card"><div className="category-name"><span>#</span>{category.name}</div><div className="meta">{category.description}</div></article></Link>
          ))}</div>
        </div>
        <aside className="community-panel"><div className="community-panel-accent" /><div className="community-panel-body"><h3>HackMate</h3><p>OpenCore USB automation with a community of builders helping builders.</p><div className="stat-row"><div className="stat"><strong>{downloads === null ? '—' : downloads.toLocaleString()}</strong><span>downloads</span></div><div className="stat"><strong>4</strong><span>channels</span></div></div></div></aside>
      </div>

      <section className="product-section">
        <div className="section-title">What it does</div>
        <div className="feature-grid">{features.map((feature) => <div className="feature-item" key={feature}><span>✓</span><p>{feature}</p></div>)}</div>
      </section>

      <section className="product-section install-grid">
        <div><div className="eyebrow">Windows</div><h2>Download and run</h2><p>Get the latest HackMate.exe release and run it as Administrator.</p><a className="primary-link" href="https://github.com/riftaway7-code/hackmate/releases/latest">Get HackMate.exe</a></div>
        <div><div className="eyebrow">Linux / macOS</div><h2>Install from source</h2><pre className="terminal"><code>git clone https://github.com/riftaway7-code/hackmate.git{`\n`}cd hackmate && python3 setup.py{`\n`}sudo .venv/bin/python3 src/hackmate.py</code></pre></div>
      </section>

      <section className="product-section">
        <div className="section-title">Generated config coverage</div>
        <div className="coverage-grid"><div><strong>Intel</strong><span>2nd–15th generation</span></div><div><strong>AMD Ryzen</strong><span>Zen through Zen 5</span></div><div><strong>Graphics</strong><span>Intel framebuffer auto-patching</span></div><div><strong>Connectivity</strong><span>Intel, Broadcom, Realtek, Atheros</span></div></div>
        <p className="coverage-note">Hardware support varies by GPU, networking, laptop model, and macOS release. HackMate analyzes the exact machine before generating a configuration.</p>
      </section>

      <section className="product-section">
        <div className="section-title">FAQ</div>
        <div className="faq-list">{faqs.map(([question, answer]) => <details key={question}><summary>{question}</summary><p>{answer}</p></details>)}</div>
      </section>
    </div>
  )
}
