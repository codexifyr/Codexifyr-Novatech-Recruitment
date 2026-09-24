import Link from "next/link";

export default function Home() {
  return <>
    <section className="hero"><div className="container hero-grid"><div>
      <span className="eyebrow">Careers at NovaTech Solutions</span>
      <h1>Build technology that moves people and businesses forward.</h1>
      <p className="lead">Join a thoughtful team solving real problems with reliable software, clear communication and room to grow.</p>
      <div className="actions"><Link className="button" href="/jobs">Explore open roles</Link><Link className="button ghost" href="/company">Meet NovaTech</Link></div>
      <div className="trust"><span>✓ Transparent hiring</span><span>✓ Human review</span><span>✓ Equal opportunity</span></div>
    </div><div className="hero-card"><span className="pulse">We&apos;re hiring</span><h2>Your next chapter could start here.</h2><p>Engineering, quality and business roles for people who value ownership and useful work.</p><div className="metric-row"><div><b>3</b><span>teams hiring</span></div><div><b>Hybrid</b><span>work culture</span></div></div></div></div></section>
    <section className="section"><div className="container"><span className="eyebrow">Why NovaTech</span><h2 className="section-title">Serious work. Supportive environment.</h2><div className="cards three">
      <article className="feature"><span>01</span><h3>Own meaningful outcomes</h3><p>Work close to the problem, contribute ideas and see your decisions reach real users.</p></article>
      <article className="feature"><span>02</span><h3>Grow with intention</h3><p>Learn through mentoring, feedback, focused challenges and a practical learning budget.</p></article>
      <article className="feature"><span>03</span><h3>Work with clarity</h3><p>Clear expectations, respectful collaboration and transparent hiring from day one.</p></article>
    </div></div></section>
    <section className="section soft"><div className="container split"><div><span className="eyebrow">How we hire</span><h2 className="section-title">A clear path from application to offer.</h2><p className="lead small">You will always know what stage you are in and what happens next.</p></div><ol className="steps"><li><b>Apply</b><span>Choose a role and share your experience.</span></li><li><b>Interview</b><span>Meet the team and work through relevant questions.</span></li><li><b>Decision</b><span>Receive a clear outcome and next steps.</span></li></ol></div></section>
    <section className="cta"><div className="container"><h2>Ready to do work you&apos;re proud of?</h2><p>Explore current opportunities and find the role that fits your strengths.</p><Link className="button light-button" href="/jobs">See open positions →</Link></div></section>
  </>;
}

