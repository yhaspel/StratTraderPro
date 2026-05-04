/** /strategies/:id — pine + description previews. */
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { firstValueFrom } from 'rxjs';
import { StrategiesApi } from '../../../core/services/strategies.api';
import { Strategy } from '../../../core/models/strategies.models';

@Component({
  selector: 'app-strategies-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, TranslateModule],
  template: `
    <div class="mx-auto max-w-4xl p-6">
      <a routerLink="/strategies" class="text-sm text-blue-600 hover:underline">← {{ 'strategies.detail.back' | translate }}</a>

      @if (loading()) {
        <p class="mt-4 text-sm text-gray-500">{{ 'strategies.detail.loading' | translate }}</p>
      }
      @if (!loading() && strategy(); as s) {
        <h1 class="text-2xl font-bold mt-2">{{ s.name }}</h1>
        <p class="text-sm text-gray-500">{{ s.description_short }}</p>

        @if (!s.is_system) {
          <div class="mt-3 inline-block bg-amber-50 border border-amber-200 text-amber-800 text-xs px-2 py-1 rounded">
            ⚠ {{ 'strategies.list.untested_banner' | translate }}
          </div>
        }

        <h2 class="text-lg font-semibold mt-6 mb-2" id="pine-heading">{{ 'strategies.detail.pine' | translate }}</h2>
        <!-- tabindex=0 + role=region + aria-labelledby satisfies WCAG 2.1.1 (Keyboard) for scrollable content. -->
        <pre tabindex="0" role="region" aria-labelledby="pine-heading"
             class="bg-gray-50 border rounded p-3 text-xs whitespace-pre-wrap overflow-auto max-h-96"><code>{{ pineText() }}</code></pre>

        <h2 class="text-lg font-semibold mt-6 mb-2" id="desc-heading">{{ 'strategies.detail.description' | translate }}</h2>
        <pre tabindex="0" role="region" aria-labelledby="desc-heading"
             class="bg-gray-50 border rounded p-3 text-xs whitespace-pre-wrap overflow-auto max-h-96"><code>{{ descText() }}</code></pre>
      }
      @if (!loading() && !strategy()) {
        <p class="mt-4 text-sm text-red-700">{{ 'strategies.detail.not_found' | translate }}</p>
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
