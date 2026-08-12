import type * as Three from 'three';
import {
  AfterViewInit,
  Component,
  ElementRef,
  NgZone,
  OnDestroy,
  ViewChild
} from '@angular/core';

@Component({
  selector: 'app-iris-hero-scene',
  standalone: true,
  templateUrl: './iris-hero-scene.component.html',
  styleUrl: './iris-hero-scene.component.scss'
})
export class IrisHeroSceneComponent implements AfterViewInit, OnDestroy {
  @ViewChild('sceneHost', { static: true }) private readonly sceneHost!: ElementRef<HTMLDivElement>;

  private three?: typeof import('three');
  private renderer?: Three.WebGLRenderer;
  private scene?: Three.Scene;
  private camera?: Three.PerspectiveCamera;
  private frameId = 0;
  private clock?: Three.Clock;
  private orbitGroup?: Three.Group;
  private isDestroyed = false;
  private readonly reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  private readonly resizeObserver = new ResizeObserver(() => this.resize());

  constructor(private readonly ngZone: NgZone) {}

  ngAfterViewInit(): void {
    this.ngZone.runOutsideAngular(() => {
      void this.bootstrapScene();
    });
  }

  ngOnDestroy(): void {
    this.isDestroyed = true;
    cancelAnimationFrame(this.frameId);
    this.resizeObserver.disconnect();
    this.renderer?.dispose();
    this.scene?.traverse((object) => {
      const mesh = object as Three.Mesh;
      if (mesh.isMesh) {
        mesh.geometry.dispose();
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        materials.forEach((material) => material.dispose());
      }
    });
  }

  private async bootstrapScene(): Promise<void> {
    this.three = await import('three');
    if (this.isDestroyed) {
      return;
    }

    this.clock = new this.three.Clock();
    this.orbitGroup = new this.three.Group();
    this.initScene(this.three);
    this.resizeObserver.observe(this.sceneHost.nativeElement);
    this.animate();
  }

  private initScene(three: typeof import('three')): void {
    const host = this.sceneHost.nativeElement;
    this.scene = new three.Scene();
    this.camera = new three.PerspectiveCamera(36, 1, 0.1, 100);
    this.camera.position.set(0, 0.25, 7.2);

    this.renderer = new three.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.8));
    this.renderer.setClearColor(0x000000, 0);
    host.appendChild(this.renderer.domElement);

    const ambient = new three.AmbientLight(0xffffff, 1.35);
    const keyLight = new three.DirectionalLight(0x7ff7e8, 2.4);
    keyLight.position.set(3, 3.4, 5);
    const rimLight = new three.PointLight(0x39b7ff, 5.2, 14);
    rimLight.position.set(-3.4, 1.8, 3.2);
    this.scene.add(ambient, keyLight, rimLight);

    this.scene.add(this.createLens(three));
    this.scene.add(this.createDataOrbit(three));
    this.scene.add(this.createDecisionPlanes(three));
    this.scene.add(this.createParticles(three));
    this.resize();
  }

  private createLens(three: typeof import('three')): Three.Group {
    const group = new three.Group();
    const sphereGeometry = new three.SphereGeometry(1.58, 72, 72);
    const sphereMaterial = new three.MeshPhysicalMaterial({
      color: 0x0fb6a5,
      emissive: 0x06302f,
      emissiveIntensity: 0.16,
      roughness: 0.16,
      metalness: 0.08,
      transmission: 0.28,
      thickness: 0.65,
      clearcoat: 0.9,
      clearcoatRoughness: 0.18,
      transparent: true,
      opacity: 0.86
    });

    const sphere = new three.Mesh(sphereGeometry, sphereMaterial);
    sphere.scale.set(1, 1, 0.28);

    const ringGeometry = new three.TorusGeometry(1.88, 0.012, 16, 160);
    const ringMaterial = new three.MeshBasicMaterial({ color: 0x57e4d2, transparent: true, opacity: 0.62 });
    const ringA = new three.Mesh(ringGeometry, ringMaterial);
    const ringB = ringA.clone();
    ringA.rotation.x = Math.PI / 2.5;
    ringB.rotation.y = Math.PI / 2.2;

    const coreGeometry = new three.SphereGeometry(0.34, 48, 48);
    const coreMaterial = new three.MeshStandardMaterial({
      color: 0x061d22,
      emissive: 0x22c9dd,
      emissiveIntensity: 0.32,
      roughness: 0.32,
      metalness: 0.22
    });
    const core = new three.Mesh(coreGeometry, coreMaterial);
    core.position.z = 0.18;

    group.add(sphere, ringA, ringB, core);
    return group;
  }

  private createDataOrbit(three: typeof import('three')): Three.Group {
    const orbit = this.orbitGroup ?? new three.Group();
    const dotGeometry = new three.SphereGeometry(0.055, 16, 16);
    const dotMaterial = new three.MeshBasicMaterial({ color: 0xd8fff9 });

    for (let i = 0; i < 42; i += 1) {
      const dot = new three.Mesh(dotGeometry, dotMaterial);
      const angle = (i / 42) * Math.PI * 2;
      const radius = 2.35 + (i % 3) * 0.15;
      dot.position.set(Math.cos(angle) * radius, Math.sin(angle * 1.2) * 0.58, Math.sin(angle) * 0.32);
      orbit.add(dot);
    }

    this.orbitGroup = orbit;
    return orbit;
  }

  private createDecisionPlanes(three: typeof import('three')): Three.Group {
    const group = new three.Group();
    const material = new three.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.14,
      side: three.DoubleSide
    });

    for (let i = 0; i < 4; i += 1) {
      const plane = new three.Mesh(new three.PlaneGeometry(1.35, 0.56), material.clone());
      plane.position.set(-2.55 + i * 1.7, -1.74 + (i % 2) * 0.18, -0.35 - i * 0.08);
      plane.rotation.x = -0.18;
      plane.rotation.y = 0.16 - i * 0.05;
      group.add(plane);
    }

    return group;
  }

  private createParticles(three: typeof import('three')): Three.Points {
    const count = 170;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i += 1) {
      positions[i * 3] = (Math.random() - 0.5) * 7;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 4.6;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 2.1;
    }

    const geometry = new three.BufferGeometry();
    geometry.setAttribute('position', new three.BufferAttribute(positions, 3));
    const material = new three.PointsMaterial({
      color: 0x7ff7e8,
      size: 0.018,
      transparent: true,
      opacity: 0.44
    });

    return new three.Points(geometry, material);
  }

  private animate(): void {
    const elapsed = this.clock?.getElapsedTime() ?? 0;
    if (this.scene && this.camera && this.renderer) {
      if (!this.reducedMotion) {
        this.scene.rotation.y = Math.sin(elapsed * 0.22) * 0.08;
        if (this.orbitGroup) {
          this.orbitGroup.rotation.y = elapsed * 0.22;
          this.orbitGroup.rotation.z = Math.sin(elapsed * 0.18) * 0.08;
        }
      }
      this.renderer.render(this.scene, this.camera);
    }

    this.frameId = requestAnimationFrame(() => this.animate());
  }

  private resize(): void {
    const host = this.sceneHost.nativeElement;
    const width = Math.max(host.clientWidth, 1);
    const height = Math.max(host.clientHeight, 1);
    if (!this.camera || !this.renderer) {
      return;
    }

    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }
}
