import type { Metadata } from "next";
import "./globals.css";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export const metadata: Metadata = { title: "Careers | NovaTech Solutions", description: "Build useful technology with NovaTech Solutions." };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return  <html
  lang="en"
  data-scroll-behavior="smooth"
  suppressHydrationWarning
>
    <body><Header/><main>{children}</main><Footer/></body></html>;
}

