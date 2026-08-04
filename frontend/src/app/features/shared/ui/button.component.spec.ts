import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ButtonComponent } from './button.component';

describe('ButtonComponent', () => {
  let fixture: ComponentFixture<ButtonComponent>;
  let component: ButtonComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [ButtonComponent] }).compileComponents();
    fixture = TestBed.createComponent(ButtonComponent);
    component = fixture.componentInstance;
  });

  function btn(): HTMLButtonElement {
    return fixture.nativeElement.querySelector('button');
  }

  it('applies the primary variant by default', () => {
    fixture.detectChanges();
    expect(btn().className).toContain('bg-accent');
  });

  it('applies the danger variant', () => {
    component.variant = 'danger';
    fixture.detectChanges();
    expect(btn().className).toContain('bg-down');
  });

  it('applies the success variant (Release actions)', () => {
    component.variant = 'success';
    fixture.detectChanges();
    expect(btn().className).toContain('bg-up');
  });

  it('renders no corner marks by default', () => {
    fixture.detectChanges();
    expect(btn().querySelectorAll('.corner').length).toBe(0);
  });

  it('renders blueprint corner marks when framed', () => {
    component.frame = true;
    fixture.detectChanges();
    expect(btn().classList).toContain('blueprint');
    expect(btn().querySelectorAll('.corner').length).toBe(4);
  });

  it('disables and marks aria-busy while loading', () => {
    component.loading = true;
    fixture.detectChanges();
    expect(btn().disabled).toBeTrue();
    expect(btn().getAttribute('aria-busy')).toBe('true');
  });

  it('emits clicked when pressed', () => {
    const spy = jasmine.createSpy('clicked');
    component.clicked.subscribe(spy);
    fixture.detectChanges();
    btn().click();
    expect(spy).toHaveBeenCalled();
  });
});
