import { render } from 'preact';
import { App } from './app';
import '../src/fonts.css';
import '../src/styles/design-system.css';
import './styles.css';
import { registerTelemetrySink } from './telemetry';

if (import.meta.env.DEV) {
	registerTelemetrySink((event) => {
		console.debug('[amprealize][telemetry]', event);
	});
}

render(<App />, document.getElementById('root') as HTMLElement);
