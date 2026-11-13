import { useTenant } from '../auth/TenantContext'
import { NotYet, PageHeader } from '../components/ui'

/** One customer: its phone system at a glance. Until the builder exists (Step 3) it says what will be here. */
export function OverviewPage() {
  const { current } = useTenant()
  return (
    <>
      <PageHeader title={current!.name} />
      <NotYet as="h2" title="Phone system" arrives="Step 3: the builder">
        <p>Set up this customer’s phone system from a template in a few minutes: sites with their emergency addresses, numbers, business hours, the main menu and the people.
          Then add phones by scanning their barcodes.</p>
      </NotYet>
    </>
  )
}
