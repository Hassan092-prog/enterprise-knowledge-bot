import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from 'react-hot-toast';

export const metadata: Metadata = {
  title: "Enterprise Knowledge & Intelligence Console",
  description: "Hybrid RRF Retrieval-Augmented Generation & Tabular SQL Analytical Agent",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-full flex flex-col bg-paper text-ink selection:bg-accent selection:text-accent-ink font-body">
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            style: {
              background: 'var(--color-paper-2)',
              color: 'var(--color-ink)',
              border: '1px solid var(--color-rule)',
              borderRadius: 'var(--radius-base)',
              fontFamily: 'var(--font-body)',
              fontSize: '0.875rem',
            },
          }}
        />
      </body>
    </html>
  );
}

