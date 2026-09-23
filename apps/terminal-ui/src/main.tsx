import { render } from "preact";
import { App } from "./app/App";
import "./styles.css";
import "./styles/charts.css";
import "./styles/components.css";
import "./styles/events.css";
import "./styles/intelligence.css";
import "./styles/market-desk.css";

render(<App />, document.getElementById("app")!);
