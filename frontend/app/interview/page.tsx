import ActionForm from "@/components/ActionForm";

export default function InterviewResponsePage() {
  return (
    <div className="page">
      <section className="page-head compact">
        <div className="container">
          <span className="eyebrow">Secure candidate action</span>
          <h1>Interview response</h1>
          <p>Confirm the proposed schedule or request another date and time from your private email link.</p>
        </div>
      </section>
      <section className="section">
        <div className="container narrow">
          <ActionForm type="interview" />
        </div>
      </section>
    </div>
  );
}

