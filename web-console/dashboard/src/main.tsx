import { render } from 'preact';
import { App } from './app';
import './styles.css';
import { registerTelemetrySink } from './telemetry';

if (import.meta.env.DEV) {
	registerTelemetrySink((event) => {
		console.debug('[amprealize][telemetry]', event);
	});
}

render(<App />, document.getElementById('root') as HTMLElement);
