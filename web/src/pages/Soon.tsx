import { NotYet } from '../components/ui'

// Pages whose features come in later steps (docs/BUILD-GUIDE.md §6). Each says plainly that it is not built and what it will hold, so nobody
// mistakes an empty page for a phone system that is failing.

export const PhonesPage = () => (
  <NotYet title="Phones" arrives="Step 4: GDMS and barcode enrollment">
    <p>Scan the barcode on a phone’s box with this device’s camera, pick the user, and the phone sets itself up when it is plugged in. Status, reboot and reassignment live here too.</p>
  </NotYet>
)

export const MonitorPage = () => (
  <NotYet title="Monitor" arrives="Step 5: the monitoring pane">
    <p>Every phone’s status from GDMS and from the phone system, trunks, and calls in progress, per site, with problems first and said in words: “the site’s internet is down”, not twenty offline phones.</p>
  </NotYet>
)

export const MyPhonePage = () => (
  <NotYet title="My phone" arrives="Step 3: the builder">
    <p>Your voicemail, greetings and call forwarding, and whether your phones are online.</p>
  </NotYet>
)

export const TemplatesPage = () => (
  <NotYet as="h2" title="Templates" arrives="Step 3: the builder">
    <p>Starting points for a new customer’s phone system (small office, medical office, church, retail), Photon’s and your own, and copies of a customer’s setup.</p>
  </NotYet>
)

export const AlertsPage = () => (
  <NotYet as="h2" title="Alerts" arrives="Step 5: the monitoring pane">
    <p>Who is told when a site’s phones all go offline, a trunk fails, the spending limit stops calls, or someone dials 911.</p>
  </NotYet>
)

export const ConsolePage = () => (
  <NotYet as="h2" title="PhotonConsole connection" arrives="Step 5: the monitoring pane">
    <p>A token that lets PhotonConsole show this phone system beside the building’s other systems and run your own alert rules on it.</p>
  </NotYet>
)

export const AuditPage = () => (
  <NotYet as="h2" title="Audit log" arrives="Step 3: the builder">
    <p>Every change to the phone system and every phone action, with who did it, including partner support.</p>
  </NotYet>
)

export const InstancesPage = () => (
  <NotYet as="h2" title="Instances" arrives="Step 1: instances and the live engine">
    <p>Photon’s FusionPBX instances: health, load, versions, drift, and the phone systems each one holds.</p>
  </NotYet>
)

export const UpstreamsPage = () => (
  <NotYet as="h2" title="Upstreams" arrives="Step 3: the builder">
    <p>PhotonVox Trunking’s upstreams (Hickory Telephone first), their order per call class, and their state on each instance.</p>
  </NotYet>
)

export const GdmsPage = () => (
  <NotYet as="h2" title="GDMS" arrives="Step 4: GDMS and barcode enrollment">
    <p>The connection to Grandstream’s device management: the API’s health, the site tree, the model templates in use.</p>
  </NotYet>
)

