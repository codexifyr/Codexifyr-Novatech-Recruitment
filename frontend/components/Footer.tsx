import Link from "next/link";
export default function Footer() {
  return <footer><div className="container footer-grid">
    <div><div className="brand light"><span className="brand-mark">N</span><span>NovaTech Solutions</span></div><p>Technology built by people who care about meaningful outcomes.</p></div>
    <div><h4>Careers</h4><Link href="/jobs">Open positions</Link><Link href="/company">Life at NovaTech</Link></div>
    <div><h4>Candidate help</h4><Link href="/interview">Interview response</Link><Link href="/offer">Offer response</Link></div>
  </div><div className="container copyright">© 2026 NovaTech Solutions. Equal opportunity employer.</div></footer>;
}

