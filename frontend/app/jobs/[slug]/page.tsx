import JobDetailClient from "@/components/JobDetailClient";
export function generateStaticParams() { return [{slug:"python-developer"},{slug:"business-development-executive"},{slug:"qa-engineer"}]; }
export default async function JobDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <JobDetailClient slug={slug}/>;
}
