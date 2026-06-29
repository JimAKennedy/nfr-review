// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
	site: 'https://jimakennedy.github.io',
	base: '/nfr-review',
	integrations: [
		starlight({
			title: 'nfr-review',
			description:
				'Non-functional design review automation — learn, use, and maintain the tool',
			social: [
				{
					icon: 'github',
					label: 'GitHub',
					href: 'https://github.com/JimAKennedy/nfr-review',
				},
			],
			customCss: ['./src/styles/custom.css'],
			sidebar: [
				{
					label: 'Learn',
					items: [
						{ label: 'What is nfr-review?', slug: 'learn/01-what-is-nfr-review' },
						{ label: 'Your First Scan', slug: 'learn/02-first-scan' },
						{ label: 'The Pipeline', slug: 'learn/03-the-pipeline' },
						{ label: 'Collectors', slug: 'learn/04-collectors' },
						{ label: 'Rules', slug: 'learn/05-rules' },
						{ label: 'Output Formats', slug: 'learn/06-output-formats' },
						{ label: 'Scoring and Maturity', slug: 'learn/07-scoring' },
						{ label: 'Hygiene System', slug: 'learn/08-hygiene' },
						{ label: 'Design Change Detection', slug: 'learn/09-design-change' },
						{ label: 'Advanced Features', slug: 'learn/10-advanced' },
						{ label: 'CI/CD Integration', slug: 'learn/11-ci-cd' },
						{ label: 'Writing Custom Rules', slug: 'learn/12-custom-rules' },
						{ label: 'Writing Custom Collectors', slug: 'learn/13-custom-collectors' },
						{ label: 'Maintaining nfr-review', slug: 'learn/14-maintaining' },
					],
				},
				{
					label: 'Reference',
					items: [
						{ label: 'CLI Reference', slug: 'reference/cli' },
						{ label: 'Configuration', slug: 'reference/config' },
						{ label: 'Rule Catalogue', slug: 'reference/rules' },
						{ label: 'Collector Reference', slug: 'reference/collectors' },
						{ label: 'Finding Fields', slug: 'reference/finding-fields' },
						{ label: 'Tech Detection', slug: 'reference/tech-detection' },
						{ label: 'Compliance Matrix', slug: 'reference/compliance' },
						{ label: 'Architecture Command', slug: 'reference/arch' },
						{ label: 'Payload Schemas', slug: 'reference/payloads' },
					],
				},
				{
					label: 'Recipes',
					items: [
						{ label: 'Scanning a Monorepo', slug: 'recipes/monorepo' },
						{ label: 'Baseline Tracking', slug: 'recipes/baseline-tracking' },
						{ label: 'Compliance Audit', slug: 'recipes/compliance-audit' },
						{ label: 'Interpreting Reports', slug: 'recipes/interpreting-reports' },
						{ label: 'Filing GitHub Issues', slug: 'recipes/github-issues' },
						{ label: 'Tuning for Large Repos', slug: 'recipes/large-repos' },
					],
				},
				{
					label: 'Appendices',
					items: [
						{ label: 'Architecture Overview', slug: 'appendices/architecture' },
						{ label: 'Glossary', slug: 'appendices/glossary' },
						{ label: 'FAQ', slug: 'appendices/faq' },
					],
				},
			],
		}),
	],
});
