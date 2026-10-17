import { defineConfig } from 'vitepress'

export default defineConfig({
  base: '/ghosttrace/',
  title: 'GHOSTTRACE',
  titleTemplate: ':title — GHOSTTRACE',
  description: 'Self-Verifying Multi-Agent Intelligence Engine built on FalkorDB',
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: true,

  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/ghosttrace/logo.svg' }],
    ['meta', { name: 'theme-color', content: '#0b0f19' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:title', content: 'GHOSTTRACE Documentation' }],
    ['meta', { property: 'og:description', content: 'Self-verifying multi-agent intelligence engine built on FalkorDB' }],
    ['meta', { property: 'og:image', content: '/ghosttrace/screenshots/0-story.png' }]
  ],

  markdown: {
    math: true
  },

  themeConfig: {
    logo: '/logo.svg',
    siteTitle: 'GHOSTTRACE',

    nav: [
      { text: 'Architecture', link: '/architecture' },
      { text: 'FalkorDB Brain', link: '/why-falkordb' },
      { text: 'The Hard Problem', link: '/hard-problem' },
      { text: 'REST API', link: '/api' },
      { text: 'Evaluation', link: '/evaluation' },
      { text: 'Demo Video', link: '/demo-script' },
      {
        text: 'v0.1.0 (Hackathon)',
        items: [
          { text: 'Judge FAQ', link: '/judge-faq' },
          { text: 'Claims Ledger', link: '/claims-ledger' },
          { text: 'Operations Guide', link: '/operations' },
          { text: 'GitHub Repository', link: 'https://github.com/HirthikBalaji/ghosttrace' }
        ]
      }
    ],

    sidebar: [
      {
        text: 'Core Overview',
        collapsed: false,
        items: [
          { text: 'Introduction & Pitch', link: '/' },
          { text: 'The Hard Problem: Open-World Containment', link: '/hard-problem' },
          { text: 'Swarm Architecture & 5-Agent Flow', link: '/architecture' },
          { text: 'Demo Walkthrough & Script', link: '/demo-script' }
        ]
      },
      {
        text: 'FalkorDB as the Brain',
        collapsed: false,
        items: [
          { text: 'Why FalkorDB is the Brain', link: '/why-falkordb' },
          { text: 'Bitemporal Graph Schema', link: '/graph-schema' },
          { text: 'Performance & Benchmarks', link: '/performance' },
          { text: 'Hot Query Latency Profiles', link: '/performance-profiles' }
        ]
      },
      {
        text: 'Formal Verification & Rigor',
        collapsed: false,
        items: [
          { text: 'Formal Claims Ledger', link: '/claims-ledger' },
          { text: 'Evaluation Suite & Soundness Gate', link: '/evaluation' },
          { text: 'Threat Model & Security Proofs', link: '/threat-model' }
        ]
      },
      {
        text: 'API & Deployment',
        collapsed: false,
        items: [
          { text: 'REST API Specification', link: '/api' },
          { text: 'Production Operations & OIDC', link: '/operations' },
          { text: 'Upstream FalkorDB Bug Report', link: '/upstream/falkordb-aof-unique-constraint-crash' }
        ]
      },
      {
        text: 'Hackathon & Judging',
        collapsed: false,
        items: [
          { text: 'Judge FAQ & Architecture Highlights', link: '/judge-faq' }
        ]
      }
    ],

    search: {
      provider: 'local'
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/HirthikBalaji/ghosttrace' }
    ],

    editLink: {
      pattern: 'https://github.com/HirthikBalaji/ghosttrace/edit/main/docs/:path',
      text: 'Suggest an edit on GitHub'
    },

    footer: {
      message: 'GhostTrace — Built with FalkorDB for WeMakeDevs Graph Hacks 2026',
      copyright: 'Released under the Apache 2.0 / MIT License'
    }
  }
})
