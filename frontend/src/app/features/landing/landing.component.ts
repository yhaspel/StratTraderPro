import { Component, ChangeDetectionStrategy } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';

@Component({
  selector: 'app-landing',
  standalone: true,
  imports: [TranslateModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="container mx-auto px-4 py-16 text-center">
      <h1 class="text-4xl font-bold text-primary-900 mb-4">
        {{ 'app.title' | translate }}
      </h1>
      <p class="text-lg text-slate-600 max-w-2xl mx-auto mb-8">
        {{ 'app.tagline' | translate }}
      </p>
      <div class="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary-50 text-primary-700 text-sm font-medium">
        {{ 'app.status' | translate }}
      </div>
    </main>
  `,
})
export class LandingComponent {}
