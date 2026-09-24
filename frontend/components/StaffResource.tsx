"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function StaffResource({title,endpoint}:{title:string;endpoint:string}){
  const router=useRouter(),[items,setItems]=useState<Record<string,unknown>[]>([]),[error,setError]=useState("");
  useEffect(()=>{api<{items:Record<string,unknown>[]}>(endpoint).then(r=>setItems(r.items)).catch(e=>{setError(e.message);router.push("/login")})},[endpoint,router]);
  const scalar=(value:unknown):string=>value===null||value===undefined?"—":typeof value==="object"?Object.values(value as Record<string,unknown>).filter(v=>typeof v!=="object").join(" · "):String(value);
  const keys=items.length?Object.keys(items[0]).filter(k=>k!=="id").slice(0,7):[];
  return <div className="resource-page"><div className="container section"><Link className="back" href="/dashboard">← Dashboard</Link><div className="table-head"><div><span className="eyebrow">Recruitment operations</span><h1>{title}</h1></div></div>{error&&<div className="notice error">{error}</div>}<section className="table-card"><div className="table-scroll"><table><thead><tr>{keys.map(k=><th key={k}>{k.replaceAll("_"," ")}</th>)}</tr></thead><tbody>{items.map((item,i)=><tr key={String(item.id||i)}>{keys.map(k=><td key={k}>{scalar(item[k])}</td>)}</tr>)}</tbody></table></div>{!items.length&&!error&&<div className="notice">No records available.</div>}</section></div></div>;
}

