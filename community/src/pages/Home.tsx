import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchCategories } from '../lib/queries'
import type { Category } from '../lib/types'

const features = [
  { title: 'Complete hardware scan', body: 'Detects CPU generation, GPU, audio codecs, ethernet, Wi-Fi, NVMe drives, Thunderbolt controllers, and other hardware that affects an OpenCore build.' },
  { title: 'macOS compatibility check', body: 'Matches the detected CPU and graphics hardware against supported macOS versions before anything is downloaded or written.' },
  { title: 'Safe USB preparation', body: 'Lists removable targets, hides internal disks, formats the selected USB, and builds the required recovery and EFI layout.' },
  { title: 'Recovery from Apple', body: 'Downloads the official macOS Recovery image directly from Apple using the same macrecovery workflow documented by Dortania.' },
  { title: 'Automatic OpenCore EFI', body: 'Selects OpenCore components and generates config.plist, SMBIOS data, ACPI tables, drivers, tools, and the kext set for the detected machine.' },
  { title: 'Framebuffer configuration', body: 'Suggests and injects appropriate Intel iGPU platform IDs for supported Sandy Bridge through Ice Lake graphics configurations.' },
  { title: 'Audio layout suggestions', body: 'Identifies common Realtek codecs and suggests AppleALC layout IDs instead of leaving users to guess through every possible alcid.' },
  { title: 'Networking support', body: 'Handles common Intel and Broadcom Wi-Fi plus Realtek, Intel, and Atheros ethernet families with the appropriate kext choices.' },
  { title: 'Config editor and validation', body: 'Includes tools for reviewing generated settings, editing config.plist, checking EFI structure, and catching unsafe or incomplete configurations.' },
  { title: 'Built for repeatable updates', body: 'Tracks OpenCore resources and generated configuration choices so users can rebuild or update an EFI without starting from scratch.' },
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
      <section className="hero hero-simple">
        <div>
          <h1>HackMate</h1>
          <p>Made with Python by a small group of three developers.</p>
          <a className="primary-link" href="https://github.com/riftaway7-code/hackmate/releases/latest">Download on GitHub</a>
        </div>
        <div className="hero-stats">
          <div><strong>{downloads === null ? '—' : downloads.toLocaleString()}</strong><span>downloads</span></div>
          <div><strong>3</strong><span>developers</span></div>
          <div><strong>4</strong><span>community channels</span></div>
        </div>
      </section>

      <div className="section-title">Browse channels</div>
      {error && <div className="error">{error}</div>}
      {!categories && !error && <div className="meta">Loading channels…</div>}
      <div className="category-grid">{categories?.map((category) => (
        <Link key={category.id} to={`/c/${category.slug}`}><article className="category-card"><div className="category-name"><span>#</span>{category.name}</div><div className="meta">{category.description}</div></article></Link>
      ))}</div>

      <section className="product-section">
        <div className="section-title">What it does</div>
        <div className="feature-grid detailed-features">{features.map((feature) => <article className="feature-item" key={feature.title}><span>✓</span><div><h3>{feature.title}</h3><p>{feature.body}</p></div></article>)}</div>
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
