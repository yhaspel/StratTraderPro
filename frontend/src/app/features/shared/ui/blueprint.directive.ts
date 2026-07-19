/** Blueprint frame ("Industry" design system) — the wireframe grammar every
 * framed surface shares: square corners, hairline `--color-divider` border and
 * four "+" corner registration marks. Apply `stpBlueprint` to a card, panel,
 * dialog or hero/submit primary button; the directive adds the `.blueprint`
 * class (styled globally in styles.scss) and appends the four corner marks.
 */
import { Directive, ElementRef, OnInit, Renderer2, inject } from '@angular/core';

@Directive({
  selector: '[stpBlueprint]',
  standalone: true,
})
export class BlueprintDirective implements OnInit {
  private readonly el = inject(ElementRef<HTMLElement>);
  private readonly renderer = inject(Renderer2);

  ngOnInit(): void {
    const host = this.el.nativeElement as HTMLElement;
    this.renderer.addClass(host, 'blueprint');
    for (const pos of ['tl', 'tr', 'bl', 'br']) {
      const corner = this.renderer.createElement('i');
      this.renderer.addClass(corner, 'corner');
      this.renderer.addClass(corner, pos);
      this.renderer.setAttribute(corner, 'aria-hidden', 'true');
      this.renderer.appendChild(host, corner);
    }
  }
}
