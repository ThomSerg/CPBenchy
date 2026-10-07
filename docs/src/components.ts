/**
 * MDX globals registry — components available inside MDX without `import`.
 * Wired via `<Content components={components} />` in `[...slug].astro`.
 * Add new components here as you build (or install) them.
 */

import { Aside } from "./components/ui/aside";
import Catalog from "./components/library/Catalog.astro";
import PackageHeader from "./components/library/PackageHeader.astro";
import PackageSource from "./components/library/PackageSource.astro";
import { Badge } from "./components/ui/badge";
import Render from "./components/Render.astro";
import { Card } from "./components/ui/card";
import { CodeGroup } from "./components/ui/code-group";
import { CardGrid } from "./components/ui/card-grid";
import { PackageManagers } from "./components/ui/package-managers";
import { Step, Steps } from "./components/ui/steps";
import { Tabs, TabItem } from "./components/ui/tabs";

export const components = {
  Aside,
  Badge,
  Catalog,
  PackageHeader,
  PackageSource,
  Card,
  CardGrid,
  CodeGroup,
  PackageManagers,
  Render,
  Step,
  Steps,
  TabItem,
  Tabs,
};
