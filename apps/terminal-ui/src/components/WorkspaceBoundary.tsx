import { Component, type ComponentChildren } from "preact";
import { StateMessage } from "./Primitives";

interface Props { children: ComponentChildren; }
interface State { error: Error | null; }

export class WorkspaceBoundary extends Component<Props, State> {
  state: State = { error: null };

  componentDidCatch(error: Error) {
    this.setState({ error });
  }

  render() {
    if (this.state.error) {
      return <StateMessage title="This workspace could not be displayed" detail="The rest of WorldState is still available. Open Data Sources for diagnostics, then try this page again." action={<button type="button" class="primary-button" onClick={() => this.setState({ error: null })}>Retry workspace</button>} />;
    }
    return this.props.children;
  }
}
