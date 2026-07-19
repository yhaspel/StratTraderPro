/** /strategies/:id — pine + description previews.
 *
 * Visual layer: "Industry" design system — condensed heading, accent back
 * link, shared warn chip, code panels as font-mono on `--color-surface`.
 */
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { firstValueFrom } from 'rxjs';
import { StrategiesApi } from '../../../core/services/strategies.api';
import { Strategy } from '../../../core/models/strategies.models';
import { StatusChipComponent } from '../../shared/ui/status-chip.component';

@Component({
  selector: 'app-strategies-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, TranslateModule, StatusChipComponent],
  template: `
    <div class="mx-auto max-w-4xl p-6">
      <a routerLink="/strategies"
         class="inline-block w-fit rounded-none px-1 text-[13px] text-accent-700 transition-colors hover:bg-accent-100">
        ← {{ 'strategies.detail.back' | translate }}
      </a>

      @if (loading()) {
        <p class="mt-4 text-sm text-neutral-700">{{ 'strategies.detail.loading' | translate }}</p>
      }
      @if (!loading() && strategy(); as s) {
        <h1 class="mt-2 font-heading text-[28px] font-semibold leading-[1.12] tracking-tight text-ink">{{ s.name }}</h1>
        <p class="text-sm text-neutral-700">{{ s.description_short }}</p>

        @if (!s.is_system) {
          <div class="mt-3">
            <app-status-chip tone="warn">
              ⚠ {{ 'strategies.list.untested_banner' | translate }}
            </app-status-chip>
          </div>
        }

        <h2 class="mt-6 mb-2 font-heading text-lg font-semibold text-ink" id="pine-heading">{{ 'strategies.detail.pine' | translate }}</h2>
        <!-- tabindex=0 + role=region + aria-labelledby satisfies WCAG 2.1.1 (Keyboard) for scrollable content. -->
        <pre tabindex="0" role="region" aria-labelledby="pine-heading"
             class="max-h-96 overflow-auto whitespace-pre-wrap rounded-none border border-divider bg-surface p-3 font-mono text-xs text-ink"><code>{{ pineText() }}</code></pre>

        <h2 class="mt-6 mb-2 font-heading text-lg font-semibold text-ink" id="desc-heading">{{ 'strategies.detail.description' | translate }}</h2>
        <pre tabindex="0" role="region" aria-labelledby="desc-heading"
             class="max-h-96 overflow-auto whitespace-pre-wrap rounded-none border border-divider bg-surface p-3 font-mono text-xs text-ink"><code>{{ descText() }}</code></pre>
      }
      @if (!loading() && !strategy()) {
        <div class="mt-4 rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
          {{ 'strategies.detail.not_found' | translate }}
        </div>
      }
    </div>
  `,
})
export class StrategiesDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private api = inject(StrategiesApi);

  loading = signal(true);
  strategy = signal<Strategy | null>(null);
  pineText = signal<string>('');
  descText = signal<string>('');

  async ngOnInit(): Promise<void> {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) { this.loading.set(false); return; }
    try {
      const res = await firstValueFrom(this.api.get(id));
      if (res.error) { this.loading.set(false); return; }
      this.strategy.set(res.data!);
      // Lazy-load file bytes — don't block the route on them.
      this._loadFiles(id);
    } finally {
      this.loading.set(false);
    }
  }

  private async _loadFiles(id: string): Promise<void> {
    try {
      const [pine, desc] = await Promise.all([
        firstValueFrom(this.api.download(id, 'PINE')),
        firstValueFrom(this.api.download(id, 'DESC')),
      ]);
      this.pineText.set(await pine.text());
      this.descText.set(await desc.text());
    } catch {
      // Best-effort previews — silently degrade.
    }
  }
}
